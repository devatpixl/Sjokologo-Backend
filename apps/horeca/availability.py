"""When can this be delivered? (K-39 … K-45)

Pure functions over the settings row, so the whole calendar is testable without
touching a view.

The requirement that shapes this module is **K-44**: a blocked day must say why
and offer the first date that works. So `reason` and `message` are real fields
in the return value, not something the frontend greys out and leaves silent.
"""
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Sum
from django.utils import timezone as djtz

from .models import BlackoutDate, CapacityOverride, HorecaOrder, HorecaSettings


@dataclass(frozen=True)
class DayAvailability:
    date: date
    available: bool
    reason: str | None       # past | lead_time | closed_weekday | blackout |
                             # capacity | horizon | paused
    message: str             # Norwegian, shown to the customer
    trays_booked: int
    trays_capacity: int

    @property
    def trays_remaining(self) -> int:
        return max(self.trays_capacity - self.trays_booked, 0)


def lead_days_for(*, has_logo: bool, products=None, cfg=None) -> int:
    """K-43 — how many days ahead this basket must be ordered.

    The longest lead among the products in it: a tray that needs hand-decorating
    sets the pace for the whole order, because they are delivered together.
    A product with no override falls back to the global setting, which is what
    the calendar uses before anything is in the basket.
    """
    cfg = cfg or HorecaSettings.load()
    default = cfg.lead_time_days_logo if has_logo else cfg.lead_time_days_plain
    overrides = [
        p.lead_time_days for p in (products or [])
        if getattr(p, 'lead_time_days', None)
    ]
    return max([default, *overrides])


def _advance(start: date, days: int, cfg, blackouts: set[date]) -> date:
    """Move `days` forward, counting only days the kitchen actually works when
    the setting says lead time is in working days.

    A kitchen that says "ten days" means ten working days — counting weekends
    would quietly promise deliveries nobody can make.
    """
    if not cfg.lead_time_in_working_days:
        return start + timedelta(days=days)
    current, counted = start, 0
    while counted < days:
        current += timedelta(days=1)
        if current.weekday() in cfg.delivery_weekdays and current not in blackouts:
            counted += 1
    return current


def earliest_eligible_date(*, has_logo: bool = False, cfg=None, now=None,
                           products=None) -> date:
    """The first date the lead time alone permits — capacity not considered."""
    cfg = cfg or HorecaSettings.load()
    now = now or djtz.localtime()
    base = djtz.localdate(now)

    # Past the cut-off, today no longer counts as a production day.
    if now.time() >= cfg.cutoff_time:
        base += timedelta(days=1)

    lead = lead_days_for(has_logo=has_logo, products=products, cfg=cfg)
    horizon = base + timedelta(days=cfg.order_horizon_days)
    blackouts = set(
        BlackoutDate.objects
        .filter(date__range=(base, horizon))
        .values_list('date', flat=True)
    )
    return _advance(base, lead, cfg, blackouts)


def availability(
    start: date, end: date, *, has_logo: bool = False,
    exclude_order=None, cfg=None, products=None,
) -> list[DayAvailability]:
    """Every day in the window, with the reason it is or is not bookable.

    Three queries for the whole range, not one per day: `tray_count` lives on
    the order and the (delivery_date, status) index carries the grouping, so
    there is no join and no N+1.
    """
    cfg = cfg or HorecaSettings.load()

    booked_qs = (
        HorecaOrder.objects
        .filter(delivery_date__range=(start, end), is_draft=False)
        .exclude(status=HorecaOrder.Status.AVBESTILT)
    )
    if exclude_order is not None:
        # So editing an order's date does not see its own trays as a blocker.
        booked_qs = booked_qs.exclude(pk=exclude_order)
    booked = {
        row['delivery_date']: row['trays'] or 0
        for row in booked_qs.values('delivery_date').annotate(trays=Sum('tray_count'))
    }

    overrides = dict(
        CapacityOverride.objects.filter(date__range=(start, end))
        .values_list('date', 'max_trays')
    )
    blackouts = dict(
        BlackoutDate.objects.filter(date__range=(start, end))
        .values_list('date', 'reason')
    )

    earliest = earliest_eligible_date(has_logo=has_logo, cfg=cfg, products=products)
    today = djtz.localdate()
    horizon = today + timedelta(days=cfg.order_horizon_days)

    days, current = [], start
    while current <= end:
        capacity = overrides.get(current, cfg.max_trays_per_day)
        used = booked.get(current, 0)
        reason, message = None, ''

        if cfg.ordering_paused:
            reason = 'paused'
            message = cfg.paused_message or 'Bestillinger er midlertidig stengt.'
        elif current < today:
            reason, message = 'past', 'Datoen har passert.'
        elif current > horizon:
            reason = 'horizon'
            message = f'Vi tar imot bestillinger inntil {cfg.order_horizon_days} dager frem.'
        elif current in blackouts:
            reason = 'blackout'
            message = blackouts[current] or 'Stengt denne dagen.'
        elif current.weekday() not in cfg.delivery_weekdays:
            reason, message = 'closed_weekday', 'Vi leverer ikke denne ukedagen.'
        elif current < earliest:
            lead = lead_days_for(has_logo=has_logo, products=products, cfg=cfg)
            unit = 'virkedager' if cfg.lead_time_in_working_days else 'dager'
            suffix = ' for brett med logo' if has_logo else ''
            reason = 'lead_time'
            message = f'Vi trenger minst {lead} {unit}{suffix}.'
        elif capacity and used >= capacity:
            reason = 'capacity'
            message = f'Fullt denne dagen — vi rekker {capacity} brett per dag.'

        days.append(DayAvailability(
            date=current,
            available=reason is None,
            reason=reason,
            message=message,
            trays_booked=used,
            trays_capacity=capacity,
        ))
        current += timedelta(days=1)

    return days


def first_available_date(*, has_logo: bool = False, trays: int = 1, cfg=None,
                         products=None):
    """K-44 — the date to suggest when the customer picks a blocked day.

    Note this must skip days that are *full* as well as days that are
    ineligible. Telling someone "earliest is Thursday" and then refusing
    Thursday because it is booked out is the bug this exists to prevent.
    """
    cfg = cfg or HorecaSettings.load()
    start = earliest_eligible_date(has_logo=has_logo, cfg=cfg, products=products)
    end = djtz.localdate() + timedelta(days=cfg.order_horizon_days)
    for day in availability(start, end, has_logo=has_logo, cfg=cfg,
                            products=products):
        if day.available and day.trays_remaining >= trays:
            return day.date
    return None

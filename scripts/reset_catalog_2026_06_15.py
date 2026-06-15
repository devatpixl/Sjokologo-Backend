"""
Catalog reset for the 2026-06-15 client refresh.

Run with:  python manage.py shell < scripts/reset_catalog_2026_06_15.py

Idempotent — safe to re-run. Updates existing rows by slug.

What it does:
1. Marks ALL existing products in_stock=False (clean slate; preserves order FKs).
2. Upserts the 9 visible products: 8 flavor variants (4 flavors x 2 sizes)
   + Sjokoladebar — Pistasjkrønsj. Sets in_stock=True on those nine.
3. Re-points the existing 3-pakning bundle to variant_group `vanlig-16` if not
   already set (kept at kr 949).

Bundle stays wired by variant_group, so the 4 new 16-biter flavors automatically
qualify for "kjøp 3 og betal 949".
"""
from apps.products.models import Product
from apps.bundles.models import BundleRule

# ── Step 1: hide everything ────────────────────────────────────────────────
hidden = Product.objects.update(in_stock=False)
print(f"Marked {hidden} existing products in_stock=False")

# ── Step 2: upsert the 9 visible products ─────────────────────────────────
FLAVORS = [
    {
        "key": "frukt-sott-med-nott",
        "label": "Frukt og søtt med en nøtt",
        "flavors": [
            "Gul/rød — Mango (melk, soya)",
            "Bronsje — Karamell (melk, soya)",
            "Rød/brun — Hasselnøtt (hasselnøtter, melk, soya)",
            "Gul — Pasjonsfrukt (melk, soya)",
        ],
        "blurb": (
            "En blanding av frukt, karamell og nøtt. Inneholder mango, karamell, "
            "hasselnøtt og pasjonsfrukt. Oppbevares mørkt ved 17 grader. "
            "Alle produkter kan inneholde spor av peanøtter og nøtter."
        ),
    },
    {
        "key": "notter-pasjonsfrukt",
        "label": "Nøtter og pasjonsfrukt",
        "flavors": [
            "Grønn/gul — Pistasjpraline (pistasj, melk, soya)",
            "Bronsje — Karamell (melk, soya)",
            "Rød/brun — Hasselnøtt (hasselnøtter, melk, soya)",
            "Gul — Pasjonsfrukt (melk, soya)",
        ],
        "blurb": (
            "For deg som elsker både nøtter og frisk frukt. Pistasjpraline, karamell, "
            "hasselnøtt og pasjonsfrukt. Oppbevares mørkt ved 17 grader. "
            "Alle produkter kan inneholde spor av peanøtter og nøtter."
        ),
    },
    {
        "key": "bare-notter",
        "label": "Bare nøtter",
        "flavors": [
            "Rød/brun — Hasselnøtt (hasselnøtter, melk, soya)",
            "Grønn/gul — Pistasj (pistasjnøtter, melk, soya)",
        ],
        "blurb": (
            "Ren nøtekjærlighet — hasselnøtt og pistasj. Oppbevares mørkt ved "
            "17 grader. Alle produkter kan inneholde spor av peanøtter og nøtter."
        ),
    },
    {
        "key": "bare-frukt",
        "label": "Bare frukt",
        "flavors": [
            "Rød — Bringebær (melk, soya)",
            "Gul — Pasjonsfrukt (melk, soya)",
            "Røg/gul — Mango (melk, soya)",
        ],
        "blurb": (
            "Friske bær og frukt — bringebær, pasjonsfrukt og mango. Oppbevares "
            "mørkt ved 17 grader. Alle produkter kan inneholde spor av peanøtter og nøtter."
        ),
    },
]

SIZES = [
    {
        "suffix": "8",
        "size": "8 biter",
        "price": 220,
        "category": "liten-sjokoladeboks",
        "variant_group": "vanlig-8",
        "name_suffix": "(8 biter)",
        # Existing VPS upload, reused across all 4 flavor variants of this size.
        "image": "products/liten-notte-bg-rem.png",
    },
    {
        "suffix": "16",
        "size": "16 biter",
        "price": 380,
        "category": "stor-sjokoladeboks",
        "variant_group": "vanlig-16",
        "name_suffix": "(16 biter)",
        "image": "products/sjokoloco-box-new.png",
    },
]

BATCH_NUMBER = "2026-06"

created, updated = 0, 0
for size in SIZES:
    for flavor in FLAVORS:
        slug = f"vanlig-{flavor['key']}-{size['suffix']}"
        defaults = {
            "name": f"Vanlig — {flavor['label']} {size['name_suffix']}",
            "category": size["category"],
            "size": size["size"],
            "price": size["price"],
            "image": size["image"],
            "flavors": flavor["flavors"],
            "blurb": flavor["blurb"],
            "in_stock": True,
            "variant_group": size["variant_group"],
            "variant_label": flavor["label"],
            "batch_number": BATCH_NUMBER,
            "batch_count": 0,
            "batch_total": 0,
        }
        obj, was_created = Product.objects.update_or_create(slug=slug, defaults=defaults)
        created += int(was_created); updated += int(not was_created)
        print(f"  {'+' if was_created else 'u'} {slug}  kr {obj.price}  in_stock={obj.in_stock}")

# Pistasjkrønsj bar
bar_defaults = {
    "name": "Sjokoladebar — Pistasjkrønsj",
    "category": "sjokoladebarer",
    "size": "80g",
    "price": 89,
    # Existing VPS upload used by the prior pistasj bar.
    "image": "products/bar-6-bg-rem_kwiMoWH.png",
    "flavors": ["Pistasjkrønsj"],
    "blurb": (
        "Håndlaget sjokoladebar med pistasjkrønsj. Oppbevares mørkt ved 17 grader. "
        "Inneholder pistasjnøtter, melk og soya. Alle produkter kan inneholde "
        "spor av peanøtter og nøtter."
    ),
    "in_stock": True,
    "variant_group": "",
    "variant_label": "",
    "batch_number": BATCH_NUMBER,
    "batch_count": 0,
    "batch_total": 0,
}
bar, was_created = Product.objects.update_or_create(slug="sjokoladebar-pistasjkronsj", defaults=bar_defaults)
created += int(was_created); updated += int(not was_created)
print(f"  {'+' if was_created else 'u'} sjokoladebar-pistasjkronsj  kr {bar.price}  in_stock={bar.in_stock}")

print(f"\nUpsert summary: {created} created, {updated} updated")

# ── Step 3: ensure bundle rule still wired to vanlig-16 ───────────────────
bundle = BundleRule.objects.filter(variant_group="vanlig-16").first()
if bundle:
    print(f"\nBundle '{bundle.name}' already wired to vanlig-16 @ kr {bundle.bundle_price}, "
          f"active={bundle.is_active}")
else:
    print("\nNo bundle rule for vanlig-16 — creating VANLIG-16-3PACK @ kr 949")
    BundleRule.objects.create(
        name="VANLIG-16-3PACK",
        description="3-pakning Vanlig (16 biter) — fri frakt",
        variant_group="vanlig-16",
        required_quantity=3,
        bundle_price=949,
        includes_free_shipping=True,
        is_active=True,
    )

# ── Step 4: final visible-products listing ────────────────────────────────
print("\nFinal in_stock=True catalog:")
for p in Product.objects.filter(in_stock=True).order_by("category", "variant_group", "variant_label", "name"):
    vg = p.variant_group or "—"
    vl = p.variant_label or "—"
    print(f"  {p.category:24s} | {p.slug:42s} | {p.name:60s} | kr {p.price} | vg={vg:10s} vl={vl}")

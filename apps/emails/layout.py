"""Shared HTML email layout for Sjoko Loco transactional mail.

The colors and typography mirror the storefront's editorial palette:
dark espresso (``#0E0906``) background, warm gold (``#C9A35B``) accent,
cream (``#F5EFE6``) text, italic Georgia serif for headings.

All CSS is inline because most mail clients strip ``<style>`` blocks.
"""

from __future__ import annotations

from html import escape


def render_layout(
    *,
    eyebrow: str,
    heading: str,
    intro_html: str = '',
    blocks_html: str = '',
    cta_url: str | None = None,
    cta_label: str | None = None,
    cta_secondary_url: str | None = None,
    cta_secondary_label: str | None = None,
    footer_lines: list[str] | None = None,
    closing_html: str | None = None,
) -> str:
    """Return a full HTML document for a transactional email.

    Args:
        eyebrow: Small uppercased tagline above the heading
            (e.g. ``'◈ Ordrebekreftelse'``).
        heading: Large italic heading. Plain text; will be HTML-escaped.
        intro_html: One or two paragraphs of intro copy. *Already HTML*
            (so callers can include ``<strong>``, etc.).
        blocks_html: Optional content placed between intro and CTA — used
            for order tables, address blocks, status boxes, etc. *Already
            HTML*.
        cta_url, cta_label: Primary gold button. Both must be provided
            to render anything.
        cta_secondary_url, cta_secondary_label: Optional secondary text
            link below the primary CTA.
        footer_lines: Small print above the sign-off (e.g. order number,
            shipping method). Each entry is plain text, joined by " · ".
        closing_html: Optional override of the italic closing line. If
            ``None``, the default "Hilsen — Team Sjoko Loco" is used.
    """
    safe_heading = escape(heading)
    safe_eyebrow = escape(eyebrow)

    cta_html = ''
    if cta_url and cta_label:
        cta_html = f'''
          <tr>
            <td style="padding:28px 36px 8px; text-align:center;">
              <a href="{escape(cta_url)}" style="display:inline-block; padding:14px 38px; background:#C9A35B; color:#0E0906; text-decoration:none; font-size:12px; font-weight:600; letter-spacing:0.18em; text-transform:uppercase;">
                {escape(cta_label)} →
              </a>
            </td>
          </tr>
'''
        if cta_secondary_url and cta_secondary_label:
            cta_html += f'''
          <tr>
            <td style="padding:0 36px 24px; text-align:center;">
              <a href="{escape(cta_secondary_url)}" style="color:rgba(245,239,230,0.7); text-decoration:underline; font-size:13px; letter-spacing:0.04em;">
                {escape(cta_secondary_label)}
              </a>
            </td>
          </tr>
'''
    elif cta_secondary_url and cta_secondary_label:
        cta_html = f'''
          <tr>
            <td style="padding:24px 36px 24px; text-align:center;">
              <a href="{escape(cta_secondary_url)}" style="color:#C9A35B; text-decoration:underline; font-size:13px; letter-spacing:0.04em;">
                {escape(cta_secondary_label)}
              </a>
            </td>
          </tr>
'''

    footer_meta_html = ''
    if footer_lines:
        safe_lines = ' &middot; '.join(escape(line) for line in footer_lines if line)
        footer_meta_html = f'''
          <tr>
            <td style="padding:16px 36px 0; text-align:center; font-size:12px; color:rgba(245,239,230,0.55); letter-spacing:0.04em;">
              {safe_lines}
            </td>
          </tr>
'''

    closing = closing_html or (
        '<p style="margin:0 0 8px; font-family: Georgia, \'Times New Roman\', serif; font-style:italic; font-size:16px; color:rgba(245,239,230,0.85);">'
        'Hilsen — Team Sjoko Loco</p>'
    )

    return f'''<!DOCTYPE html>
<html lang="no">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_heading}</title>
</head>
<body style="margin:0; padding:0; background:#0E0906; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color:#F5EFE6;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#0E0906;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table role="presentation" width="560" cellspacing="0" cellpadding="0" border="0" style="max-width:560px; background:#161009; border:1px solid rgba(201,163,91,0.18);">

          <!-- Wordmark -->
          <tr>
            <td style="padding:36px 36px 0; text-align:center;">
              <div style="font-family: Georgia, 'Times New Roman', serif; font-style:italic; font-weight:300; font-size:28px; color:#C9A35B; letter-spacing:0.02em;">
                Sjoko Loco
              </div>
              <div style="margin-top:6px; font-size:10.5px; letter-spacing:0.32em; color:rgba(245,239,230,0.55); text-transform:uppercase;">
                {safe_eyebrow}
              </div>
            </td>
          </tr>

          <!-- Heading -->
          <tr>
            <td style="padding:36px 36px 8px;">
              <h1 style="margin:0 0 14px; font-family: Georgia, 'Times New Roman', serif; font-style:italic; font-weight:300; font-size:34px; line-height:1.12; color:#F5EFE6;">
                {safe_heading}
              </h1>
              <div style="font-size:15px; line-height:1.65; color:rgba(245,239,230,0.78);">
                {intro_html}
              </div>
            </td>
          </tr>

          <!-- Content blocks (order summary, status box, address, etc.) -->
          {blocks_html}

          {cta_html}

          {footer_meta_html}

          <!-- Footer -->
          <tr>
            <td style="padding:24px 36px 36px; border-top:1px solid rgba(201,163,91,0.18); text-align:center;">
              {closing}
              <p style="margin:0; font-size:12px; line-height:1.65; color:rgba(245,239,230,0.55);">
                Sjoko Loco &middot; Håndlaget konfekt fra Ås
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''


def render_status_box(label: str, value: str) -> str:
    """Gold-bordered card used for order-status callouts."""
    return f'''
          <tr>
            <td style="padding:18px 36px 8px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:rgba(201,163,91,0.08); border:1px solid rgba(201,163,91,0.35);">
                <tr>
                  <td style="padding:18px 22px;">
                    <div style="font-size:10.5px; letter-spacing:0.32em; color:#C9A35B; text-transform:uppercase; margin-bottom:6px;">
                      {escape(label)}
                    </div>
                    <div style="font-family: Georgia, 'Times New Roman', serif; font-weight:300; font-size:22px; color:#F5EFE6;">
                      {escape(value)}
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
'''


def render_kv_block(label: str, rows: list[tuple[str, str]]) -> str:
    """Two-column label/value block used for shipping address, order details."""
    safe_rows = ''.join(
        f'''
                <tr>
                  <td style="padding:4px 0; width:42%; font-size:13px; color:rgba(245,239,230,0.55); vertical-align:top;">{escape(k)}</td>
                  <td style="padding:4px 0; font-size:13px; color:#F5EFE6; vertical-align:top;">{escape(v)}</td>
                </tr>'''
        for k, v in rows
    )
    return f'''
          <tr>
            <td style="padding:18px 36px 0;">
              <div style="font-size:10.5px; letter-spacing:0.32em; color:#C9A35B; text-transform:uppercase; margin-bottom:10px;">
                {escape(label)}
              </div>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">{safe_rows}
              </table>
            </td>
          </tr>
'''


def render_items_table(rows: list[tuple[str, int, str]], totals: list[tuple[str, str]]) -> str:
    """Order line-items table. ``rows`` are (name, qty, line_total).
    ``totals`` are (label, value) — e.g. Subtotal, Frakt, Totalt.
    """
    item_rows = ''.join(
        f'''
                <tr>
                  <td style="padding:8px 0; border-bottom:1px solid rgba(201,163,91,0.12); font-size:13.5px; color:#F5EFE6;">{escape(name)}</td>
                  <td style="padding:8px 0; border-bottom:1px solid rgba(201,163,91,0.12); font-size:13.5px; color:rgba(245,239,230,0.6); text-align:center; width:60px;">× {qty}</td>
                  <td style="padding:8px 0; border-bottom:1px solid rgba(201,163,91,0.12); font-size:13.5px; color:#F5EFE6; text-align:right; width:110px;">{escape(line_total)}</td>
                </tr>'''
        for name, qty, line_total in rows
    )

    total_rows = ''
    for i, (label, value) in enumerate(totals):
        is_last = i == len(totals) - 1
        weight = 'font-weight:600;' if is_last else ''
        color = '#F5EFE6' if is_last else 'rgba(245,239,230,0.7)'
        border = '' if is_last else 'border-bottom:1px dotted rgba(201,163,91,0.18);'
        total_rows += f'''
                <tr>
                  <td colspan="2" style="padding:8px 0; {border} font-size:13.5px; color:{color}; {weight}">{escape(label)}</td>
                  <td style="padding:8px 0; {border} font-size:13.5px; color:{color}; text-align:right; {weight}">{escape(value)}</td>
                </tr>'''

    return f'''
          <tr>
            <td style="padding:18px 36px 0;">
              <div style="font-size:10.5px; letter-spacing:0.32em; color:#C9A35B; text-transform:uppercase; margin-bottom:10px;">
                ◈ Din bestilling
              </div>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">{item_rows}{total_rows}
              </table>
            </td>
          </tr>
'''

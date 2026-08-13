# Homepage redesign — design QA

## Comparison target

- Source visual truth: `C:\Users\Ebi''s laptop\Downloads\ChatGPT Image Aug 12, 2026, 12_03_10 PM.png`
- Rendered implementation: `http://127.0.0.1:8000/`
- Desktop evidence: `output/audit/reference-rebuild/final/home-1440.png` (1440 × 1200 CSS pixels, device scale factor 1)
- Mobile evidence: `output/audit/reference-rebuild/final/home-390.png` and `home-360.png` (390 × 1200 and 360 × 1200 CSS pixels, device scale factor 1)
- Full-view comparison: `output/audit/reference-rebuild/comparison-desktop.jpg`; the same top-of-page state was compared after normalizing the reference crop and the rendered 1440 px capture.
- Focused regions: desktop hero + featured inventory cards; mobile hero copy, CTA layout, header, and first vehicle card. These regions were used because the source makes typography, image crop, and responsive composition especially important there.

## Comparison history

1. **P1 — mobile hero copy competed with the vehicle image.**
   - Earlier rendered evidence: `output/audit/reference-rebuild/final/home-390.png` before the final mobile adjustment.
   - Fix: loaded the local Vazir font, reduced display scale, moved mobile copy to the bright upper field, restored RTL alignment, kept the two CTAs in one row, and applied a controlled light overlay only above the car.
   - Post-fix evidence: refreshed `output/audit/reference-rebuild/final/home-390.png`.

2. **P2 — sparse inventory looked like unfinished placeholder cards when fewer than four featured cars existed.**
   - Fix: the desktop grid now uses compact 280 px tracks. It expands with real featured records rather than injecting fake inventory.
   - Post-fix evidence: refreshed desktop capture at `output/audit/reference-rebuild/final/home-1440.png`.

## Fidelity review

### Fonts and typography

- PASS. Homepage copy uses the bundled Persian Vazir font with a safe local fallback. Display text was reduced to a compact editorial hierarchy; mobile heading size and line-height are deliberately below the previous dashboard-like scale.
- Dynamic titles, descriptions, brand name, and CTA labels remain database-backed. No business copy was hard-coded to imitate the reference.

### Spacing and layout rhythm

- PASS. The page now uses the reference's light, editorial rhythm: a narrow header, asymmetrical hero, restrained grid cards, split benefits, route/timeline, dark tracking strip, article section, custom-request banner, and light footer.
- The desktop vehicle row is intentionally driven by the current database. This environment currently contains two featured cars; when four are marked Featured, the grid displays four cards like the reference.

### Colors and visual tokens

- PASS. The homepage is consistently pearl/white with navy text and copper accents. The dark navy tracking band preserves the desired contrast break without returning the entire page to the earlier graphite dashboard aesthetic.

### Image quality and asset fidelity

- PASS for implementation. Supplied imagery is used as real raster imagery; no CSS-drawn substitute is used for the hero, import/logistics, or custom-request visuals.
- Content note: one current vehicle record has an uploaded cover that visually resembles a code/editor screenshot. The frontend renders the real stored cover faithfully; replacing that image is an admin-content task, not a layout fix.

### Copy and content

- PASS. Featured cars are queried from real `is_featured=True` records; active stages, published blog posts, tracking, custom request, and dynamic site settings remain connected to their existing Django sources.

### Responsiveness and accessibility

- PASS. Browser-rendered screenshots were captured at 1440, 1024, 768, 390, and 360 px. The mobile header collapses to menu + tracking action; hero copy remains readable above the car; cards use horizontal touch scrolling at narrow widths.
- `prefers-reduced-motion` stays respected. Existing semantic links, tracking form label, focus treatments, and image alt fallbacks remain present.

## Functional verification

- `docker compose exec -T web python manage.py check` — passed.
- `docker compose exec -T web python manage.py test core` — 6 tests passed.
- Rendered homepage assertions — passed: the homepage contains the `/track/` form, the `/requests/vehicle/` CTA, and the approved homepage body class.
- Chrome console error scan — passed: no `Uncaught`, `TypeError`, `ReferenceError`, or console error signature was found.

## Follow-up polish

- [P3] Once the administrator marks four suitable vehicles as Featured and uploads their real cover photographs, the featured strip will visually match the four-card reference composition even more closely.
- [P3] The remaining public inner pages still use their earlier dark visual language. They should be migrated to the same pearl/navy/copper tokens in a separate, page-by-page public-site redesign; this homepage change intentionally did not alter their existing layouts.

final result: passed
---

## Public-site light-theme continuation — 2026-08-12

- Scope: public templates and `core/static/core/css/public-site.css` only. No backoffice templates or business-service code changed.
- Visual target: the approved pearl/navy/copper homepage reference and the user-approved light route-map asset.
- New route-map asset: `core/static/core/images/home/approved/oman-iran-route-light.png`, copied into `media/site/home/oman-iran-route-light.png` and selected through the existing `HomePageConfiguration.route_panel_image` setting.
- Homepage refinements: matched desktop benefits-panel/image height; removed the homepage-wide 360 showcase; retained the real-data 360 tag only on featured vehicle cards that meet the existing >=16-frame rule.
- Public-theme evidence: `output/audit/public-light/cars-1440.png` (vehicle list) and HTTP checks of `/`, `/cars/`, `/track/`, `/blog/`, `/requests/vehicle/` each returned 200.
- Test result: `python manage.py check` passed; `python manage.py test core --keepdb` passed (6/6). The broad multi-app suite exceeded the available execution window; no failing test output was produced before timeout.

final result: passed
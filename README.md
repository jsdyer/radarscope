# Radar Scope

A static Canadian Internet observation desk at [coolcode.ca/radarscope/](https://coolcode.ca/radarscope/), built from saved Cloudflare Radar API captures.

<!-- coolcode:guide -->
Inspect seven days of hourly Canadian HTTP traffic and compare its daily rhythm with the United States or United Kingdom. Each country is normalized independently to its own maximum (0–1), so the curves compare shape, not traffic volume or market share. IPv4/IPv6 percentages describe the observed HTTP request mix. Canadian outage annotations cover a separate 30-day source window and are not an exhaustive outage register. Choose a retained capture, inspect gaps and source dates, or open/export a local snapshot without an API key in your browser.
<!-- /coolcode:guide -->

## What the measurements mean

The source is **Cloudflare Radar**, an aggregate view of the traffic Cloudflare observes. It does not measure all Canadian Internet traffic, all ISPs, or everyone's connection quality. Traffic changes alone do not identify causes or prove outages.

Three independent requests retrieve hourly HTTP traffic for `CA`, `US`, and `GB` over `7d`, with `normalization=MIN0_MAX`. Cloudflare defines this as a proportion of the maximum in that response, scaled 0–1. Because requests are separate, each country has its own maximum. Equal heights across countries are **not equal request counts**. Historical captures also have separate normalization windows: they preserve what was observed at collection time, rather than forming an absolute-volume trend. The display and exports retain the source normalization.

Separate `IP_VERSION` requests use `normalization=PERCENTAGE`. IPv4 and IPv6 are shares of observed HTTP requests at each time, not traffic totals, bandwidth or population adoption. Missing numeric values stay null. Missing hourly timestamps become explicit null gaps; neither chart lines nor calculations should invent zeros. Source timestamps are normalized to UTC.

Outage annotations are fetched for Canada over `30d`. The source can include outages and traffic anomalies. Description, start/end time, scope, ASN, source-reported cause/type and evidence link are retained. An absent end date means no end time was supplied, not independently verified ongoing disruption. Causes are attributed source statements. No annotation is not proof that no outage occurred. An annotation might concern one provider or area rather than the whole country. No causal relationship is inferred between a chart dip and an annotation.

## Collection and scope

The exact repository Actions secret is **`CLOUDFLARE_RADAR_API_TOKEN`**. It is sent only as a Bearer authorization header in the Python collector. Never put the token in a URL, public file, page script or browser form. No Cloudflare account or zone is changed.

Endpoints on `https://api.cloudflare.com/client/v4`:

| Data | Endpoint and parameters |
| --- | --- |
| HTTP shape | `/radar/http/timeseries?location=CA&dateRange=7d&aggInterval=1h&normalization=MIN0_MAX` (also US, GB) |
| IP shares | `/radar/http/timeseries_groups/IP_VERSION?location=CA&dateRange=7d&aggInterval=1h&normalization=PERCENTAGE` (also US, GB) |
| Annotations | `/radar/annotations/outages?location=CA&dateRange=30d&limit=100&offset=0` |

The current generic dimension endpoint uses uppercase `IP_VERSION`. The generated API schema omits dynamic series properties on some endpoints; the collector requires exactly one timestamp-bearing series in each one-country response and validates its fields. Unknown response structure stops collection instead of guessing a curve. Source `meta.normalization`, hourly aggregation, date range, update timestamp, confidence metadata and units are retained.

A normal daily collection makes seven requests; annotation pagination can raise this to eleven, at 100 rows/page with a hard **500-annotation bound**. Reaching the cap is visibly marked as truncated. Responses are limited to 8 MB; timeseries to 192 hourly points. The source's usual seven-day response is around 168 points; shorter responses are kept as source coverage, never completed with invented values. Every source response retains a content SHA-256 and safe endpoint/parameter provenance. No raw response or token is stored.

Requests specify the documented uppercase `format=JSON` enum. They are separated by at least one second, use 45-second timeouts and at most three attempts for transient/429 errors. Numeric `Retry-After` up to 60 seconds is honoured; longer delays stop the run for a future retry. Logs identify only the endpoint, country, attempt, elapsed time and HTTP status or network-failure category; tokens, headers and raw response bodies are never logged. Cloudflare documents a general client limit of 1,200 requests per five minutes per user/account token (shared with other API use); endpoint-specific controls may also apply. This bounded collector stays far below that general quota under normal operation.

## Daily archives and deployment

The workflow runs **daily at 09:37 UTC** (`37 9 * * *`), on manual dispatch, pushes and PRs. First pushes collect when the baseline is pending; ordinary code pushes use saved ready data. PRs build offline. A missing secret on an initial push may publish the explicit pending/local-import state. Invalid credentials or any source failure prevent deployment and preserve the prior successful view. Scheduled/manual collection requires the token.

A complete validated capture is written to `data/current.json`. Small hub metadata lives in `data/index.json`. Changed data appends an immutable JSON file in `archive/YYYY-MM/` and an entry with SHA-256 to `data/history.json`. Identical data preserves the original capture timestamp and archive, updating the successful check date. History is not pruned automatically. The UI can load retained captures directly; overlapping seven-day windows are still separate observations of source data, not a combined or de-duplicated long-term series.

CI tests, builds offline, runs desktop/mobile browser flows, commits validated source captures and deploys Pages. Source failures happen before any replacement. Build dates are separate from source update, capture and check dates. GitHub can stop schedules in inactive public repositories after 60 days, so the page always shows freshness rather than promising live data.

## Sources, licence and privacy

Primary documentation inspected 2026-11-22:

- [Radar overview and data licence](https://developers.cloudflare.com/radar/)
- [HTTP time series](https://developers.cloudflare.com/api/resources/radar/subresources/http/methods/timeseries/)
- [Current dimension time series](https://developers.cloudflare.com/api/resources/radar/subresources/http/methods/timeseries_groups_v2/)
- [Normalization](https://developers.cloudflare.com/radar/concepts/normalization/) and [comparison rules](https://developers.cloudflare.com/radar/get-started/making-comparisons/)
- [Outage interpretation](https://developers.cloudflare.com/radar/investigate/outages/) and [annotation endpoint](https://developers.cloudflare.com/api/resources/radar/subresources/annotations/subresources/outages/methods/get/)
- [API limits](https://developers.cloudflare.com/fundamentals/api/reference/limits/)

Data: **Cloudflare Radar**, [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). CoolCode normalizes the representation, inserts explicit missing-hour gaps, and presents the data without claiming Cloudflare endorsement. Retain source, licence and modification notice when reusing exports. Noncommercial terms apply to source data; the software licence does not relicense it.

Filters, imports and exports run in the browser. Local files are held only in tab memory. Opening a retained snapshot fetches a static same-site file; opening a provider/evidence link contacts that site. A CoolCode counter records aggregate opens without filters or uploaded files. The public site never requests or receives the API token.

## Development

```sh
node --test tests/*.test.mjs
python3 -m unittest discover -s tests -v
python3 scripts/build.py
python3 -m http.server 8000 --directory dist
```

`python3 scripts/collect.py` performs an explicitly authorized refresh with the token already in the environment. Add `--if-missing` to use an existing ready capture. The app and build need only Python/Node standard libraries. CI installs test-only Playwright for complete import/filter/export/history and mobile flow verification. Test-only fixtures are never shipped as observations. `dist/` is not committed.

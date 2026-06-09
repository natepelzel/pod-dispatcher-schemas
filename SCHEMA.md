# Pod Dispatcher schema format

Every supported podcast app/platform is described by **one YAML file** at the
root of this repository. Schemas are purely declarative — URL patterns and
string templates interpreted by the native engine. No executable code, ever
(this is also what keeps OTA schema updates within Apple's guidelines for the
future iOS app).

Schemas are validated in CI against
[`pod-dispatcher.schema.json`](pod-dispatcher.schema.json).
Run the validator locally:

```bash
pip install -r tools/requirements.txt
python tools/validate_schemas.py
```

## File anatomy

```yaml
id: example-app          # kebab-case, must match the filename (example-app.yml)
name: Example App        # shown in the UI
homepage: https://example.app

source:                  # optional — how to parse this platform's incoming links
  ...
target:                  # optional — how to deep link into this app
  ...
```

A schema must contain a `source` block, a `target` block, or both — never
neither. Apple Podcasts is source-only (you can't set it as your player… yet);
Pocket Casts is target-only until someone maps its share URLs.

After adding a schema file, add its filename to
[`manifest.json`](manifest.json) — that's the index both the
app's OTA refresh and the bundled-asset loader read.

## The `source` block

Describes how to recognise a platform's share URLs and resolve them to the
**canonical podcast identity**: the RSS feed URL, plus episode info when
available.

```yaml
source:
  hosts:                       # lowercase hostnames, no scheme
    - podcasts.apple.com
    - itunes.apple.com
  patterns:                    # tried in order — first match wins
    - level: episode           # put stricter patterns first
      path: '^/(?:(?<country>[a-z]{2})/)?podcast/(?:[^/]+/)?id(?<showId>\d+)/?$'
      query:                   # required query params: name → regex over value
        i: '^(?<episodeId>\d+)$'
    - level: show
      path: '^/(?:(?<country>[a-z]{2})/)?podcast/(?:[^/]+/)?id(?<showId>\d+)/?$'
  android:                     # optional — narrows what the Android app intercepts
    paths:
      - prefix: /podcast
  resolve:
    type: itunes-api
    params:
      id: '{showId}'
```

### Matching semantics

1. The URL's host must appear in `hosts` (exact, case-insensitive).
2. `patterns` are tried top to bottom; the first one that fully matches wins.
3. `path` is a regex (Java/Kotlin syntax) matched against the URL path.
4. Every key in `query` must be present as a query parameter and its value
   must match the given regex. A pattern with a `query` block therefore only
   matches URLs carrying those parameters — list it *before* the looser
   pattern without it.
5. **Named capture groups** — `(?<showId>\d+)` — from both the path and query
   regexes are collected into the capture map, and are then available as
   `{showId}` etc. in resolver templates.

### `android.paths` — interception narrowing

The Android app **generates its manifest intent filters from the schemas at
build time** — hosts come from `hosts`, and the optional `android.paths`
block narrows interception to specific URL paths so unrelated links on a
shared host (e.g. Spotify music) keep opening normally:

```yaml
source:
  hosts:
    - open.spotify.com
  android:
    paths:                          # entries combine as OR
      - prefix: /show               # android:pathPrefix — literal prefix
      - pattern: '/intl-.*/show/.*' # android:pathPattern — Android glob
                                    # ('.' any char, '.*' wildcard), NOT a regex
```

Without an `android` block, every path on the source's hosts is intercepted.
Keep `paths` in sync with what `patterns` can actually parse — intercepting a
link the resolver then fails on bounces the user through the fallback dialog.

> ⚠️ Android limitation: intent filters are baked in at build time, so a
> schema with a brand-new host is intercepted only from the next app release
> (no manual manifest edit needed — it's generated). OTA updates can only
> change how already-released hosts parse.

### Resolvers

Resolver types are implemented natively; the schema only configures them.

#### `itunes-api`

Calls the public iTunes Lookup API. Show-level:
`lookup?id=<id>&entity=podcast` → `results[0].feedUrl`.

```yaml
resolve:
  type: itunes-api
  params:
    id: '{showId}'            # template over captured groups
    episodeId: '{episodeId}'  # optional — enables episode-level resolution
```

When `episodeId` is set and an episode-level pattern matched, the engine calls
`lookup?id=<id>&entity=podcastEpisode` and finds the episode whose `trackId`
equals the rendered `episodeId` (Apple's `?i=` URL parameter). That yields
`{episodeGuid}`, `{episodeTitle}` and `{episodeUrl}` (the enclosure/audio URL)
for target templates. The lookup only returns recent episodes; older ones
gracefully degrade to show-level resolution.

#### `scrape`

Fetches a page and extracts the feed URL (and optionally the iTunes id).
Steps are tried in order; the first non-empty result wins.

```yaml
resolve:
  type: scrape
  url: 'https://podnews.net/podcast/{showId}'   # optional — page to fetch,
                                                # templated over captures;
                                                # defaults to the incoming URL
  feedUrl:
    - css: 'link[type="application/rss+xml"]'   # CSS selector…
      attr: href                                # …and attribute (default href;
                                                # 'text' reads text content)
    - jsonld: 'associatedMedia.contentUrl'      # dotted path into any
                                                # <script type="application/ld+json">
                                                # block; numeric segments index arrays
  itunesId:                                     # optional — enables Apple-id-keyed
    - css: 'a[href^="https://pca.st/itunes/"]'  # target links from this source
      attr: href
      pattern: 'itunes/(\d+)'                   # optional regex; first capture
                                                # group becomes the value
```

The `url` template makes "lookup pages" possible: the Spotify schema, for
example, can't get a feed from spotify.com, so it scrapes the Podnews page
for the captured Spotify show id instead.

#### `podcast-index`

Reserved. Podcast Index requires API credentials (which must live in the app
build, never in schemas), so this resolver is accepted by the format but not
yet enabled in the engine.

## The `target` block

Describes how to deep link into an app given the canonical identity.

```yaml
target:
  android:
    package: au.com.shiftyjelly.pocketcasts   # intent is pinned to this package
  links:
    show:
      - 'pktc://subscribe/{feedUrl|strip-scheme}'
    episode: []          # no public episode deep link
  episodeFallback: show  # episode links open the show instead (default)
```

* `links.show` / `links.episode` are template lists tried in order until one
  launches successfully.
* A template referencing an unavailable variable is skipped — that's the
  per-template fallback.
* If an episode-level link produces no usable episode template,
  `episodeFallback: show` (the default) falls back to the show links;
  `none` fails instead.

The Android app generates its manifest `<queries>` entry (Android 11+
package visibility) from `android.package` at build time — nothing to
declare manually.

### Canonical template variables

| Variable        | Availability                                                  |
| --------------- | ------------------------------------------------------------- |
| `{feedUrl}`     | always                                                        |
| `{itunesId}`    | when resolved via the iTunes API                              |
| `{episodeGuid}` | when the resolver pinned down an episode                      |
| `{episodeTitle}`| when the resolver pinned down an episode                      |
| `{episodeUrl}`  | when the resolver pinned down an episode (enclosure/audio URL)|

### Template filters

| Filter          | Effect                                          |
| --------------- | ----------------------------------------------- |
| `urlencode`     | percent-encodes the value                       |
| `strip-scheme`  | removes a leading `https://` / `http://` / etc. |
| `base64url`     | URL-safe base64, no padding (RFC 4648 §5)       |

Syntax: `{variable}` or `{variable|filter}`.

## Contribution checklist

1. Create `<id>.yml` with `id` matching the filename.
2. Add the filename to `manifest.json`.
3. Run `python tools/validate_schemas.py`.
4. For a **source**: add an `android.paths` block if the host serves
   non-podcast links too. The schema is all you edit — the Android manifest
   (intent filters, `<queries>`) is generated from the schemas at build
   time. New hosts start being intercepted with the next app release.
5. Include a couple of real example URLs in the PR description so reviewers
   can verify the patterns.

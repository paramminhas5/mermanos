# Merman OS

Merman OS is the music side of Param OS. It reads your Ableton sets and your library, digs for obscure new releases, and gives you one daily page: what to listen to, what to check out, what to talk about, what you are working on, and your artist goals. No AI runs in it.

## Use it on a Mac (no terminal)

1. Download **Merman OS.app** from the zip your assistant gave you (or this repo), and drag it to Applications.
2. Double-click it. The first time it asks for your email, sets itself up (a couple of minutes), schedules a daily 08:00 refresh and opens the dashboard in your browser.
3. Every time after that, double-clicking just opens the dashboard at http://127.0.0.1:8765/ . The buttons on the page refresh your data or dig for new music.

If macOS says it cannot verify the app, right-click it, choose Open, then Open again. You only do this once.

Your taste list lives on your Mac only, in `~/.crate/seeds.txt`. The online page at paramminhas.com/mermanos is a read-only copy without file paths.

Everything below is the command line, if you ever want it. The command is `mermanos` (`crate` still works).

A personal crate-digging agent that runs on your own machine. It organises your library, builds a taste profile from what you actually own, digs for obscure records through label and collaborator graphs, takes your productions apart against references, and prepares posts that stay in your voice.

It does **not** download from streaming services. See "Getting music in" below.

## Install

    python3 -m venv .venv && source .venv/bin/activate
    pip install -e ".[llm]"          # drop [llm] if you never want LLM-assisted wording
    mermanos init                        # creates ~/.crate
    $EDITOR ~/.crate/config.toml      # library, inbox, your own tracks, contact email

Optional keys (environment variables, never stored in config):

| variable | what it adds |
|---|---|
| `LASTFM_API_KEY` | Last.fm listener counts as a second obscurity signal |
| `DISCOGS_TOKEN` | how many collectors own a release, the best signal for underground records |
| `LISTENBRAINZ_TOKEN` | higher rate limits (popularity works without it) |
| `ANTHROPIC_API_KEY` | only for `posts.mode = "draft"` |

## First run

    mermanos scan                  # reads tags from library_root and own_music_dir
    mermanos report                # codecs, albums with lossy tracks, untagged files
    mermanos organize              # DRY RUN: shows the plan and writes it to ~/.crate/reports
    mermanos organize --apply      # moves files. Every move is journalled.
    mermanos organize --undo       # puts the last run back exactly as it was

Layout is `Artist/Album (Year)/NN - Title.ext`. Files missing artist or title go to `_review`. Exact duplicates are moved to `_duplicates`. Nothing is ever deleted and nothing is overwritten.

## Getting music in

Buy it (Bandcamp, Qobuz, Beatport, Boomkat, the label's own shop) or use legitimately free downloads, and drop the files in your inbox:

    mermanos ingest                # dry run: verifies FLACs (uses `flac -t` if installed), skips lossy copies of tracks you own losslessly
    mermanos ingest --apply        # files them into the library and marks matching wantlist entries as owned

`crate wantlist` writes `~/.crate/reports/wantlist.md` with search links for each record you marked wanted. There is no Monochrome/Tidal downloader on purpose: those tools pull streams the artists and labels are not paid for, and the whole point of this project is finding small artists and supporting them.

## Discovery

    mermanos taste                 # what the agent thinks you like, and why
    mermanos discover              # first run takes minutes (rate limits), reruns are cached
    mermanos candidates            # ranked, each with the path that found it
    mermanos want 12 31            # mark records you want to buy
    mermanos skip 7                # never show again

How it finds things: your top artists, then the small labels they release on (labels with more than `max_label_size` releases are ignored as pivots), then everyone else on those labels, plus collaborators and band members from MusicBrainz. Each candidate gets a **fit** score (how many strong paths lead to it) and an **obscurity** score (how few people have listened: ListenBrainz always, Last.fm and Discogs if you add keys). `obscurity` in the config is a dial: 0 ignores popularity, 1 squares it so only the deep cuts survive. Try `crate discover --obscurity 1.0`.

Put artists you love but don't own in `~/.crate/seeds.txt`. They count towards your taste.

## Studio: learning to make better music

    mermanos studio teardown track.flac                      # tempo, key, loudness, spectral balance, bar-aligned arrangement map
    mermanos studio compare mine.wav --refs ref1.flac ref2.flac
    mermanos studio analyze --limit 40                       # builds measurements for your library, your own tracks first
    mermanos studio gaps                                     # where your tracks differ most from the music you collect
    mermanos studio lesson                                   # picks one track to study for your biggest gap
    mermanos studio note "title" "what I learned" [track]    # your notebook, in your words
    mermanos studio notes

This measures. It does not have taste and it will not tell you a track is good. A difference from your references is a place to listen, not a rule.

## Posts that stay yours

1. Put 15+ of your real posts in `~/.crate/voice/posts.txt`, separated by a line containing `---`. `crate voice show` prints what it measured (casing, length, punctuation, whether you use hashtags or emoji).
2. `crate post new 12` creates `~/.crate/queue/post_0012.md` with verified facts (artist, release, label, year, listener count).
3. You write the TAKE section: what you actually thought. Nothing is written without it.
4. `crate post finalize 12`
   - `scaffold` mode (default): your take, verbatim, plus a plain facts line.
   - `draft` mode: an LLM may reword your take in your voice. It is told not to add opinions, adjectives about the sound or backstory, and its output is rejected and retried if the linter finds stock phrases, dashes, or invented-sounding constructions.
5. Edit the file, then `crate post approve 12`. The linter blocks em dashes, stock AI phrases ("hidden gem", "sonic journey", "not just X but Y"...), and anything that never names the record. It also compares against your habits (exclamation marks, hashtags, length).
6. `crate post export` prints approved posts. **Nothing posts itself.** You paste it where you want it.

It learns from you: approved posts join your voice samples, and words you repeatedly cut from drafts go on a personal avoid list.

Honest limit: if you use `draft` mode, an LLM touched the wording. Use `scaffold` if you need every word to be yours.

## Weekly run

    mermanos weekly                # scan, ingest dry run, discover, wantlist, studio analysis, post scaffolds for records you now own
    mermanos weekly --apply        # also files the inbox

    # cron, Mondays 09:00
    0 9 * * 1  /path/to/.venv/bin/crate weekly --apply >> ~/.crate/weekly.log 2>&1

Report lands in `~/.crate/reports/weekly_YYYY-MM-DD.md`. Post scaffolds are only created for records you own, so you never write about something you haven't heard.

## What leaves your machine

Artist names go to MusicBrainz, ListenBrainz (and Last.fm / Discogs if keyed). In `draft` mode, your voice samples, the facts and your take go to Anthropic. Audio files never leave your machine.

## Known limits

- MusicBrainz is community-edited. Obscure electronic, club and regional scenes are well covered, some others are thin.
- ListenBrainz popularity undercounts artists whose listeners don't use ListenBrainz. Add Last.fm and Discogs keys for better obscurity scores.
- Bandcamp blocks automated access, so it is only used for search links.
- Key detection is a guess when major/minor is ambiguous. Tempo detection is accurate on steady dance music and weaker on rubato material.
- `draft` mode was tested with a stub model, not a live API call.

## Tests

    pip install -e ".[dev]" && pytest


## Merman OS: the daily machine (no AI, no credits)

```
./install.sh          # once: venv, config, library scan, 8am schedule, first run
crate daily           # what the schedule runs: Ableton sets + library + discovery (weekly refresh) -> dashboard.html and state.json
crate serve           # open the dashboard locally; Want and Skip buttons write to your database
crate schedule --at 08:00 --install
```

`~/.crate/state.json` is the contract other systems (Param OS) read: schema, lane, headline numbers, today's listen/talk/check-out lists, studio, discovery, library, goals. `goals.json` in the same folder is yours to edit.
Everything runs on your machine. The only network calls are MusicBrainz and ListenBrainz for discovery, at most weekly.

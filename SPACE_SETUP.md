# Deploying live via Hugging Face Spaces (Docker)

This is the alternative to the Render setup in DEPLOYMENT.md -- same app
(`app/`), same trimmed `deploy_data/` snapshot, but running in a Docker
container on Hugging Face's free CPU tier (~16GB RAM vs. Render's 512MB,
sleeps only after ~48h idle vs. Render's ~15min).

## What's already set up in this repo

- `Dockerfile` -- builds the Flask app with `requirements-web.txt` against
  `deploy_data/`, serves on port 7860 (what Spaces' Docker SDK expects),
  runs as a non-root user.
- `.dockerignore` -- keeps the image to just what's needed (`app/`,
  `deploy_data/`, `run.py`, `requirements-web.txt`); excludes the full data
  pipeline, training scripts, and local-only files.

I have not been able to actually build or run this Dockerfile in this
session -- there's no Docker available in this sandbox to test with. Spaces
will build it for you and show build logs if something's wrong, but it's
worth a local `docker build` first if you have Docker installed, to catch
issues before pushing.

## Steps

1. **Create the Space.** Go to [huggingface.co/new-space](https://huggingface.co/new-space):
   - Owner: your account
   - Space name: e.g. `nepse-intelligence`
   - License: pick one (MIT is fine)
   - **Space SDK: Docker** (this is the important one -- not Gradio/Streamlit)
   - Space hardware: CPU basic (free)
   - Visibility: Public or Private, your call

2. **Push this repo's code to the Space.** A Space is its own git repo.
   Hugging Face shows you the clone URL on the Space's page after creation --
   something like:
   ```
   git remote add space https://huggingface.co/spaces/<your-username>/nepse-intelligence
   git push space main
   ```
   (You'll be prompted for Hugging Face credentials -- an access token from
   your HF account settings, not your Hugging Face password, the same way
   GitHub now requires a personal access token instead of a password.)

   Alternative: Spaces also supports linking a GitHub repo for automatic
   sync on every push, configurable from the Space's Settings tab, if you'd
   rather not maintain a second git remote.

3. **Wait for the build.** The Space page shows live build logs. Same slow
   step as Render -- installing torch is the bulk of the build time.

4. **You get a URL** like `https://<your-username>-nepse-intelligence.hf.space`.

## Keeping the Space's data current

Same as Render (see DEPLOYMENT.md's last section) -- regenerate and push
`deploy_data/`:
```
python examples/build_deploy_snapshot.py
git add deploy_data/
git commit -m "Refresh deploy_data snapshot"
git push space main     # or origin main, if using GitHub auto-sync
```

## Running both Render and Spaces at once

Nothing stops you from deploying to both -- they read the same
`deploy_data/` snapshot and the same `Dockerfile`/`render.yaml` don't
conflict. Compare the two once both are live and drop whichever fits your
needs less well.

Security hardening and incident response
=======================================

Exposed secret found
--------------------
- A SendGrid API key was committed in `paintomics4.ini:19`.
- The value has been removed from the repo. Treat the key as compromised.

Immediate actions
-----------------
- Rotate the SendGrid API key in the SendGrid dashboard.
- Redeploy with the new key provided via environment, NOT in source control.

How to provide secrets
----------------------
- Use systemd `Environment=` entries, `EnvironmentFile=` or uwsgi `--envfile`.
- Example: copy `.env.example` to a secure location and point uwsgi to it with
  `envfile = /etc/paintomics/paintomics.env` (do not commit that file).

Git history cleanup (optional but recommended)
----------------------------------------------
Use one of the following to purge the old key from history:

Option A: git filter-repo (recommended)
1. Install: `pip install git-filter-repo` (or from your package manager).
2. Run: `git filter-repo --path paintomics4.ini --invert-paths` if only that file
   contained secrets, or use `--replace-text` to scrub specific strings.
3. Force-push: `git push --force --all && git push --force --tags`.

Option B: BFG Repo-Cleaner
1. Download BFG jar.
2. Run: `java -jar bfg.jar --replace-text replacements.txt repo.git`.
3. Force-push as above.

After history rewrite
---------------------
- Invalidate any forks/mirrors and notify collaborators to re-clone.
- Rotate any other secrets that may have been exposed.

Prevent regressions
-------------------
- Keep `node_modules/` and `.idea/` out of the repo (see `.gitignore`).
- Run secret scanning before pushing: `gitleaks detect --config=.gitleaks.toml`.
- Avoid logging sensitive environment variables.

# Publish through GitHub Actions

Repository: https://github.com/julianfnunez/chicken-counter

Put the contents of this chicken-counter folder at the repository root:
Dockerfile and counter.py must not be nested inside another chicken-counter folder.
Include .github/workflows/publish.yml, .dockerignore and .gitignore.
Never commit your real .env or data folder.

The workflow tests first, then builds a linux/amd64 image and publishes to
ghcr.io/julianfnunez/chicken-counter on pushes to main. It uses the built-in
GITHUB_TOKEN; no additional Actions secrets are required. latest tracks main.
Push a tag such as v1.0.0 to publish that version; SHA tags are also generated.
For a fixed deployment, use a version or digest instead of latest.

Watch the repository's Actions tab for Test and publish container.
After the first successful publish, open your GitHub profile's Packages,
select chicken-counter, then Package settings and change visibility to Public.
New GHCR packages default to private, independently of repository visibility.
Making the package public allows ZimaOS to pull without registry credentials.

In ZimaOS Docker properties, use:
ghcr.io/julianfnunez/chicken-counter:latest
Keep your existing environment variables and persistent /data volume.
No ports, privileged mode or command override are needed.

Or use the provided compose.registry.yaml:

    docker compose -f compose.registry.yaml pull
    docker compose -f compose.registry.yaml up -d

Do not run this alongside another chicken-counter instance against the same data.
For updates, repeat pull and up -d. Changing latest in GHCR does not automatically
update an already running container.

If pushing with Git from your existing project folder:

    git init
    git add counter.py Dockerfile compose.yaml compose.registry.yaml .env.example .gitignore .dockerignore README.md DEPLOY-ZIMA.md PUBLISH-GITHUB.md tests .github
    git commit -m "Add chicken counter and GHCR publishing"
    git branch -M main
    git remote add origin https://github.com/julianfnunez/chicken-counter.git
    git push -u origin main

If origin already exists, use git remote set-url origin with that URL instead.
Use your normal GitHub authentication; do not put tokens in remote URLs.

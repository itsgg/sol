# TypeScript and JavaScript steps in every root with a package.json: the
# dependencies from package-lock.json when they are missing or stale, types
# where there is a tsconfig.json, Biome where it is a dependency, and the
# package's own test script. Sourced by tools/gate.

typescript_turn() {
    # A fresh clone (the landing check's, a worker's first session, CI's) has no
    # node_modules: install from the lock, development tools included, and record
    # the lock's fingerprint only once the install succeeded, so a changed lock or
    # a failed install installs again and nothing else does.
    each_root package-lock.json npm-ci sh -c 'want=$(sha256sum package-lock.json | cut -d" " -f1); [ "$(cat node_modules/.gate-install 2>/dev/null)" = "$want" ] || { rm -f node_modules/.gate-install; npm ci --include=dev --no-audit --no-fund --loglevel=error && echo "$want" > node_modules/.gate-install; }'
    each_root package.json tsc sh -c '[ ! -f tsconfig.json ] || npx --no-install tsc --noEmit'
    each_root package.json biome sh -c '[ ! -x node_modules/.bin/biome ] || npx --no-install biome ci .'
    each_root package.json npm-test npm test --silent
}

typescript_full() {
    each_root package.json npm-ls npm ls --depth=0
    each_root package.json npm-audit npm audit --audit-level=high
}

typescript_nightly() {
    :
}

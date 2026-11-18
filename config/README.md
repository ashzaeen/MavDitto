# Local configuration

This folder holds your own brand-voice profile, knowledge base, and component
catalog (`brand-voice.json`, `knowledge-base.json`, `components.json`).

They are **not included in this repository** and are git-ignored. Generate them
from your own sources with the dashboard's Setup Wizard.

## Quick start: seed a starter profile

```bash
python scripts/seed_config.py            # installs config/seed/uta/ into this folder
```

`config/seed/<profile>/` holds ready-made starter files. The bundled `uta` profile is derived from
material The University of Texas at Arlington publishes on the public web; each knowledge-base fact
has its `source_url`. It is an example and a convenience, not an official UTA product, and it is
UTA's content (see the repository's `NOTICE`). The script never overwrites an existing file unless
you pass `--force`.

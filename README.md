# Home Assistant Toolbox

[![Home Assistant](https://img.shields.io/badge/Home_Assistant-Custom_resources-41BDF5?logo=home-assistant)](https://www.home-assistant.io/)

A collection of custom resources for Home Assistant.

## 📦 Resources

- **[`quirks`](quirks/)** — Custom ZHA quirks (Home Assistant **2026.7.0+**).
- **[`blueprints/automation`](blueprints/automation/)** — Automation blueprints.
- **[`templates`](templates/)** — Template entities.

## ⚙️ Installation

<details>
<summary><b>Blueprints</b></summary>

| Blueprint | Import |
| --- | --- |
| Aqara W100 | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Fnokside%2Fha-toolbox%2Fmain%2Fblueprints%2Fautomation%2Faqara_w100.yaml) |

Or import manually:

1. Open a blueprint file in [`blueprints/automation`](blueprints/automation/).
2. Copy the **Raw** file URL.
3. In Home Assistant, go to **Settings → Automations & scenes → Blueprints → Import blueprint**.
4. Paste the URL and click **Import**.

</details>

<details>
<summary><b>ZHA Custom Quirks</b></summary>

1. Configure the custom quirks path in `configuration.yaml` if it is not already set:

   ```yaml
   zha:
     custom_quirks_path: /config/your_custom_quirks_folder
   ```

2. Copy the required `.py` files from [`quirks`](quirks/) to the directory specified in `custom_quirks_path`.
3. Restart Home Assistant.
4. Re-pair or reconfigure the device if needed.

</details>

<details>
<summary><b>Templates</b></summary>

See the official documentation:

- [Template integration](https://www.home-assistant.io/integrations/template/)

</details>

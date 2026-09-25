# Contributing / Cómo contribuir

Thanks for helping improve Noviark! / ¡Gracias por ayudar a mejorar Noviark!

- **Bugs and ideas**: open an [issue](../../issues/new/choose) with steps to reproduce, your OS and the model/provider you used. / Abre un issue con los pasos, tu sistema y el modelo que usabas.
- **Pull requests**: keep them small and focused, and test on at least one OS. By submitting a PR you agree that Noviark Labs may use your contribution under the [project license](LICENSE.md) and its commercial licenses. / Al enviar un PR aceptas que Noviark Labs pueda usar tu aporte bajo la licencia del proyecto y sus licencias comerciales.
- **Never include API keys**, `datos/` or `claves.vault` in issues, logs or PRs. / Nunca incluyas claves, `datos/` ni `claves.vault`.

## Development / Desarrollo
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python noviq_app.py      # native window / ventana nativa
python app.py            # server only / solo el servidor (http://127.0.0.1:7860)
```

# MLB Quant Engine v3310 Railway Fixed

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Railway
Railway uses the included `Procfile`:
```bash
web: streamlit run app.py --server.port=$PORT --server.address=0.0.0.0
```

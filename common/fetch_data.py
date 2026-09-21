"""Download the three public datasets once into common/data and print their shape."""
from pathlib import Path
import httpx, pandas as pd
D = Path(__file__).parent / "data"; D.mkdir(exist_ok=True)
B = "https://huggingface.co/datasets/{}/resolve/refs%2Fconvert%2Fparquet/{}/0000.parquet"
FILES = {
    "banking77_test.parquet": B.format("mteb/banking77", "default/test"),
    "banking77_train.parquet": B.format("mteb/banking77", "default/train"),
    "snips_test.parquet": B.format("benayas/snips", "default/test"),
    "yelp_test.parquet": B.format("Yelp/yelp_review_full", "yelp_review_full/test"),
}
for name, url in FILES.items():
    p = D / name
    if not p.exists():
        r = httpx.get(url, follow_redirects=True, timeout=120); r.raise_for_status(); p.write_bytes(r.content)
    df = pd.read_parquet(p)
    print("==", name, df.shape, list(df.columns))
    print(df.head(3).to_string(max_colwidth=90))
    for c in df.columns:
        if df[c].nunique() < 200 and c != "text":
            print("  labels in", c, ":", df[c].nunique(), sorted(df[c].unique().tolist())[:80])

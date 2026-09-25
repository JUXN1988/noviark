// Incremento atómico de contadores en Netlify Blobs (escritura condicional por etag, con reintentos)
export async function bump(store, key, apply) {
  for (let i = 0; i < 6; i++) {
    const cur = await store.getWithMetadata(key, {type: "json"});
    const data = (cur && cur.data) || {};
    apply(data);
    const res = await store.setJSON(key, data, cur ? {onlyIfMatch: cur.etag} : {onlyIfNew: true});
    if (!res || res.modified !== false) return data;
    await new Promise(r => setTimeout(r, 40 + Math.random() * 120));
  }
}
export const inc = (o, k, n = 1) => { o[k] = (o[k] || 0) + n; };

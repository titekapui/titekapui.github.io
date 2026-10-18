const APP = "https://DOMAIN-KAMU/";   // alamat peta kamu

const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export default {
  async fetch(req, env) {
    const u = new URL(req.url);
    const lat = parseFloat(u.searchParams.get("lat"));
    const lon = parseFloat(u.searchParams.get("lon"));
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180)
      return Response.redirect(APP, 302);

    // Gambar peta dengan marker api (API key tersembunyi di server)
    if (u.pathname === "/img") {
      const api = `https://maps.geoapify.com/v1/staticmap?style=osm-bright&format=jpeg&width=1200&height=630`
        + `&center=lonlat:${lon},${lat}&zoom=13`
        + `&marker=lonlat:${lon},${lat};type:awesome;color:%23d93000;size:large;icon:fire`
        + `&apiKey=${env.GEOAPIFY_KEY}`;
      const r = await fetch(api, { cf: { cacheTtl: 86400, cacheEverything: true } });
      return new Response(r.body, {
        status: r.status,
        headers: { "content-type": "image/jpeg", "cache-control": "public, max-age=86400" }
      });
    }

    // Halaman perantara: berisi meta OG, lalu pengunjung dialihkan ke peta
    const lang = ["ace", "id", "en"].includes(u.searchParams.get("lang")) ? u.searchParams.get("lang") : "id";
    const title = esc((u.searchParams.get("t") || "Titik api terdeteksi").slice(0, 120));
    const desc = esc((u.searchParams.get("d") || "Lihat lokasi titik api di Titek Apui Monitor").slice(0, 200));
    const la = lat.toFixed(4), lo = lon.toFixed(4);
    const target = `${APP}?maps=${la},${lo},15&pin=${la},${lo}&lang=${lang}`;
    const img = `${u.origin}/img?lat=${la}&lon=${lo}`;

    return new Response(`<!DOCTYPE html><html lang="${lang}"><head><meta charset="utf-8">
<title>${title}</title>
<meta property="og:type" content="website">
<meta property="og:site_name" content="Titek Apui Monitor">
<meta property="og:title" content="${title}">
<meta property="og:description" content="${desc}">
<meta property="og:image" content="${img}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:url" content="${esc(u.href)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${title}">
<meta name="twitter:description" content="${desc}">
<meta name="twitter:image" content="${img}">
<meta http-equiv="refresh" content="0;url=${esc(target)}">
</head><body><script>location.replace(${JSON.stringify(target)})</script></body></html>`,
      { headers: { "content-type": "text/html;charset=utf-8", "cache-control": "public, max-age=3600" } });
  }
};

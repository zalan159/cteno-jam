// Songs are managed with their per-song token (X-Jam-Owner). The server returns it once in the upload /
// import response; the web app keeps it in localStorage "jam.owned". These helpers let the tests clean up
// what they created, the same way a person's browser would.
export const ownedTokens = page => page.evaluate(() => { try { return JSON.parse(localStorage.getItem("jam.owned")) || {}; } catch (e) { return {}; } });
export const tokenInPage = async (page, id) => (await ownedTokens(page))[id] || null;

// upload through the API (no browser): returns { id, token, body }
export async function uploadApi(request, file, fields = {}) {
  const r = await request.post("/api/songs", { multipart: { file, ...fields } });
  const body = await r.json().catch(() => ({}));
  return { status: r.status(), id: body.id, token: body.owner_token, body };
}

export async function deleteWithToken(request, id, token) {
  if (!id) return null;
  const r = await request.delete(`/api/songs/${id}`, { headers: token ? { "X-Jam-Owner": token } : {} }).catch(() => null);
  return r && r.status();
}

// delete a song this page's browser uploaded or imported (its token is in the page's localStorage)
export async function deleteFromPage(page, request, id) {
  return deleteWithToken(request, id, await tokenInPage(page, id));
}

/* ============================================================
   Waste Segregation - tiny fetch-based API client.
   All backend calls go through here so auth headers / error
   handling stay in one place.
   ============================================================ */

const WasteSegAPI = (() => {
  const BASE = ""; // same-origin: Flask serves both API and frontend

  function token() {
    return localStorage.getItem("wastesegregation_token");
  }

  async function request(method, path, body) {
    const headers = { "Content-Type": "application/json" };
    const t = token();
    if (t) headers["Authorization"] = "Bearer " + t;

    let res;
    try {
      res = await fetch(BASE + path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (err) {
      throw new Error("Network error - is the backend server running?");
    }

    let data = null;
    try {
      data = await res.json();
    } catch (e) {
      /* no body */
    }

    if (res.status === 401) {
      // token missing/expired - bounce to login
      WasteSegAuth.logout(true);
      throw new Error((data && data.error) || "Session expired, please log in again.");
    }

    if (!res.ok) {
      throw new Error((data && data.error) || `Request failed (${res.status})`);
    }
    return data;
  }

  /* Separate path for file uploads: no Content-Type header is set here on
     purpose - the browser sets it automatically (with the correct
     multipart boundary) when the body is a FormData object. */
  async function uploadFile(path, formData) {
    const headers = {};
    const t = token();
    if (t) headers["Authorization"] = "Bearer " + t;

    let res;
    try {
      res = await fetch(BASE + path, { method: "POST", headers, body: formData });
    } catch (err) {
      throw new Error("Network error - is the backend server running?");
    }

    let data = null;
    try {
      data = await res.json();
    } catch (e) {
      /* no body */
    }

    if (res.status === 401) {
      WasteSegAuth.logout(true);
      throw new Error((data && data.error) || "Session expired, please log in again.");
    }
    if (!res.ok) {
      throw new Error((data && data.error) || `Request failed (${res.status})`);
    }
    return data;
  }

  return {
    get: (path) => request("GET", path),
    post: (path, body) => request("POST", path, body),
    put: (path, body) => request("PUT", path, body),
    del: (path) => request("DELETE", path),
    uploadFile: (path, formData) => uploadFile(path, formData),
  };
})();
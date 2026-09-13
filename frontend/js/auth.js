/* ============================================================
   Waste Segregation - session helpers (localStorage-backed JWT session).
   ============================================================ */

const WasteSegAuth = (() => {
  const TOKEN_KEY = "wastesegregation_token";
  const ROLE_KEY = "wastesegregation_role";
  const USER_KEY = "wastesegregation_user";
  const PROFILE_KEY = "wastesegregation_profile";

  function save(loginResponse) {
    localStorage.setItem(TOKEN_KEY, loginResponse.token);
    localStorage.setItem(ROLE_KEY, loginResponse.role);
    localStorage.setItem(USER_KEY, JSON.stringify(loginResponse.user || {}));
    localStorage.setItem(PROFILE_KEY, JSON.stringify(loginResponse.profile || {}));
  }

  function isLoggedIn() {
    return !!localStorage.getItem(TOKEN_KEY);
  }

  function role() {
    return localStorage.getItem(ROLE_KEY);
  }

  function user() {
    try { return JSON.parse(localStorage.getItem(USER_KEY) || "{}"); }
    catch (e) { return {}; }
  }

  function profile() {
    try { return JSON.parse(localStorage.getItem(PROFILE_KEY) || "{}"); }
    catch (e) { return {}; }
  }

  function householdCode() {
    return profile().household_code || null;
  }

  function collectorCode() {
    return profile().collector_code || null;
  }

  function logout(silent) {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(ROLE_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(PROFILE_KEY);
    if (!silent) {
      window.location.href = "/login.html";
    }
  }

  function homeForRole(r) {
    r = r || role();
    if (r === "HOUSEHOLD") return "/pages/household.html";
    if (r === "COLLECTOR") return "/pages/collector.html";
    if (r === "ADMIN") return "/pages/admin.html";
    return "/login.html";
  }

  /** Call at the top of any protected page. Optionally restrict to roles. */
  function guard(allowedRoles) {
    if (!isLoggedIn()) {
      window.location.href = "/login.html";
      return false;
    }
    if (allowedRoles && allowedRoles.length && !allowedRoles.includes(role())) {
      window.location.href = homeForRole();
      return false;
    }
    return true;
  }

  return { save, isLoggedIn, role, user, profile, householdCode, collectorCode, logout, homeForRole, guard };
})();
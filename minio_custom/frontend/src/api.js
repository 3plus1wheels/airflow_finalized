const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

function getCookie(name) {
  return document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`))
    ?.split("=")
    .slice(1)
    .join("=") || "";
}

export async function apiRequest(path, { token, ...options } = {}) {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(String(options.method || "GET").toUpperCase())) {
    const csrfToken = getCookie("csrftoken");
    if (csrfToken) headers.set("X-CSRFToken", decodeURIComponent(csrfToken));
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    credentials: "include",
    headers,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    const apiError = new Error(error.detail || "Request failed");
    apiError.status = response.status;
    throw apiError;
  }

  if (response.status === 204) return null;
  return response.json();
}

export function login(username, password) {
  return apiRequest("/auth/token/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function logout() {
  return apiRequest("/auth/logout/", { method: "POST" });
}

export function getMe() {
  return apiRequest("/me/");
}

function buildQuery(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `?${query}` : "";
}

export function listUsers(token, params = {}) {
  return apiRequest(`/users/${buildQuery(params)}`, { token });
}

export function createUser(token, user) {
  return apiRequest("/users/", {
    token,
    method: "POST",
    body: JSON.stringify(user),
  });
}

export function updateUser(token, id, user) {
  return apiRequest(`/users/${encodeURIComponent(id)}/`, {
    token,
    method: "PATCH",
    body: JSON.stringify(user),
  });
}

export function deactivateUser(token, id) {
  return apiRequest(`/users/${encodeURIComponent(id)}/`, {
    token,
    method: "DELETE",
  });
}

export function listVisibilityGrants(token, params = {}) {
  return apiRequest(`/visibility-grants/${buildQuery(params)}`, { token });
}

export function createVisibilityGrant(token, grant) {
  return apiRequest("/visibility-grants/", {
    token,
    method: "POST",
    body: JSON.stringify(grant),
  });
}

export function deleteVisibilityGrant(token, id) {
  return apiRequest(`/visibility-grants/${encodeURIComponent(id)}/`, {
    token,
    method: "DELETE",
  });
}

export function listGroups(token, params = {}) {
  return apiRequest(`/groups/${buildQuery(params)}`, { token });
}

export function getGroup(token, id) {
  return apiRequest(`/groups/${encodeURIComponent(id)}/`, { token });
}

export function createGroup(token, group) {
  return apiRequest("/groups/", {
    token,
    method: "POST",
    body: JSON.stringify(group),
  });
}

export function updateGroup(token, id, group) {
  return apiRequest(`/groups/${encodeURIComponent(id)}/`, {
    token,
    method: "PATCH",
    body: JSON.stringify(group),
  });
}

export function deleteGroup(token, id) {
  return apiRequest(`/groups/${encodeURIComponent(id)}/`, {
    token,
    method: "DELETE",
  });
}

export function createBucket(token, name, options = {}) {
  return apiRequest("/buckets/", {
    token,
    method: "POST",
    body: JSON.stringify({ name, ...options }),
  });
}

export function listBuckets(token) {
  return apiRequest("/buckets/", { token });
}

export function listObjects(token, bucket, { prefix = "", continuationToken = "", maxKeys = 100 } = {}) {
  const params = new URLSearchParams({ max_keys: String(maxKeys) });
  if (prefix) params.set("prefix", prefix);
  if (continuationToken) params.set("continuation_token", continuationToken);
  return apiRequest(`/buckets/${encodeURIComponent(bucket)}/objects/?${params.toString()}`, { token });
}

export function rewindBucket(token, bucket, rewindTo) {
  return apiRequest(
    `/buckets/${encodeURIComponent(bucket)}/rewind/?rewind_to=${encodeURIComponent(rewindTo)}`,
    { token }
  );
}

export function uploadObject(token, bucket, file, key) {
  const formData = new FormData();
  formData.append("file", file);
  if (key) formData.append("key", key);

  return apiRequest(`/buckets/${encodeURIComponent(bucket)}/objects/`, {
    token,
    method: "POST",
    body: formData,
  });
}

export async function downloadObject(token, bucket, key, versionId = "") {
  const versionParam = versionId ? `&version_id=${encodeURIComponent(versionId)}` : "";
  const response = await fetch(
    `${API_BASE_URL}/buckets/${encodeURIComponent(bucket)}/objects/download/?key=${encodeURIComponent(key)}${versionParam}`,
    {
      credentials: "include",
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    const apiError = new Error(error.detail || "Request failed");
    apiError.status = response.status;
    throw apiError;
  }

  return response.blob();
}

export function shareObject(token, bucket, key, expiresIn, { preview = false, versionId = "" } = {}) {
  const previewParam = preview ? "&preview=true" : "";
  const versionParam = versionId ? `&version_id=${encodeURIComponent(versionId)}` : "";
  return apiRequest(
    `/buckets/${encodeURIComponent(bucket)}/objects/share/?key=${encodeURIComponent(key)}&expires_in=${encodeURIComponent(expiresIn)}${previewParam}${versionParam}`,
    { token }
  );
}

export function getObjectTags(token, bucket, key) {
  return apiRequest(
    `/buckets/${encodeURIComponent(bucket)}/objects/tags/?key=${encodeURIComponent(key)}`,
    { token }
  );
}

export function saveObjectTags(token, bucket, key, tags) {
  return apiRequest(
    `/buckets/${encodeURIComponent(bucket)}/objects/tags/?key=${encodeURIComponent(key)}`,
    {
      token,
      method: "PUT",
      body: JSON.stringify({ tags }),
    }
  );
}

export function listObjectVersions(token, bucket, key) {
  return apiRequest(
    `/buckets/${encodeURIComponent(bucket)}/objects/versions/?key=${encodeURIComponent(key)}`,
    { token }
  );
}

export function deleteObject(token, bucket, key, versionId = "") {
  const versionParam = versionId ? `&version_id=${encodeURIComponent(versionId)}` : "";
  return apiRequest(
    `/buckets/${encodeURIComponent(bucket)}/objects/?key=${encodeURIComponent(key)}${versionParam}`,
    {
      token,
      method: "DELETE",
    }
  );
}

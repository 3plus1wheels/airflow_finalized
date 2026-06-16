import {
  ArrowLeft,
  BookOpenText,
  CheckCircle,
  ClipboardCheck,
  Copy,
  Download,
  FileText,
  Folder,
  LogOut,
  Share2,
  Shield,
  Plus,
  RefreshCw,
  Search,
  ShoppingBasket,
  Tag,
  Trash2,
  Upload,
  Eye,
  EyeOff,
  FolderPlus,
  History,
  Link,
  LockKeyhole,
  User,
  Users,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { defaultStyles, FileIcon } from "react-file-icon";
import {
  createUser,
  createBucket,
  createGroup,
  createVisibilityGrant,
  deleteGroup,
  deactivateUser,
  deleteVisibilityGrant,
  deleteObject,
  downloadObject,
  getGroup,
  getMe,
  getObjectTags,
  listBuckets,
  listGroups,
  listObjects,
  listObjectVersions,
  listUsers,
  listVisibilityGrants,
  login,
  logout,
  rewindBucket,
  saveObjectTags,
  shareObject,
  updateGroup,
  updateUser,
  uploadObject,
} from "./api";
import "./styles.css";

function getRoute() {
  const path = window.location.pathname;
  if (path.startsWith("/browser/")) {
    return {
      page: "browser",
      bucket: decodeURIComponent(path.slice("/browser/".length)),
    };
  }
  if (path === "/browser") return { page: "browser", bucket: "" };
  return { page: "login", bucket: "" };
}

function pushRoute(path) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function buildObjectEntries(objects, prefix, filter, pendingFolders = []) {
  const normalizedPrefix = prefix || "";
  const normalizedFilter = filter.trim().toLowerCase();
  const folders = new Map();
  const files = [];

  function addFolder(folderKey, lastModified) {
    if (!folderKey.startsWith(normalizedPrefix)) return;

    const remainder = folderKey.slice(normalizedPrefix.length);
    if (!remainder) return;

    const slashIndex = remainder.indexOf("/");
    if (slashIndex < 0) return;

    const name = remainder.slice(0, slashIndex);
    if (!name) return;

    const visibleFolderKey = `${normalizedPrefix}${name}/`;
    const existing = folders.get(visibleFolderKey);
    const itemModified = lastModified ? new Date(lastModified).getTime() : 0;
    const existingModified = existing?.last_modified ? new Date(existing.last_modified).getTime() : 0;

    folders.set(visibleFolderKey, {
      type: "folder",
      key: visibleFolderKey,
      name,
      size: null,
      last_modified: itemModified > existingModified ? lastModified : existing?.last_modified,
    });
  }

  for (const folderKey of pendingFolders) {
    addFolder(folderKey);
  }

  for (const item of objects) {
    if (!item.key.startsWith(normalizedPrefix)) continue;

    const remainder = item.key.slice(normalizedPrefix.length);
    if (!remainder) continue;

    const slashIndex = remainder.indexOf("/");
    if (slashIndex >= 0) {
      addFolder(`${normalizedPrefix}${remainder.slice(0, slashIndex + 1)}`, item.last_modified);
      continue;
    }

    files.push({
      ...item,
      type: "file",
      name: remainder,
    });
  }

  return [...folders.values(), ...files]
    .filter((entry) => entry.name.toLowerCase().includes(normalizedFilter))
    .sort((a, b) => {
      if (a.type !== b.type) return a.type === "folder" ? -1 : 1;
      return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
    });
}

function getParentPrefix(prefix) {
  const parts = prefix.split("/").filter(Boolean);
  parts.pop();
  return parts.length ? `${parts.join("/")}/` : "";
}

function normalizeFolderPath(value) {
  return value
    .split("/")
    .map((part) => part.trim())
    .filter(Boolean)
    .join("/");
}

function normalizePrefix(value) {
  return String(value || "").trim().replace(/^\/+/, "");
}

function prefixMatchesKey(prefix, key) {
  const normalizedPrefix = normalizePrefix(prefix);
  const normalizedKey = normalizePrefix(key);
  if (!normalizedPrefix) return true;
  if (normalizedPrefix.endsWith("/")) return normalizedKey.startsWith(normalizedPrefix);
  return normalizedKey === normalizedPrefix || normalizedKey.startsWith(`${normalizedPrefix}/`);
}

function getObjectDisplayName(key = "", prefix = "") {
  const visibleName = prefix && key.startsWith(prefix) ? key.slice(prefix.length) : key;
  return visibleName.split("/").filter(Boolean).pop() || key || "Unnamed object";
}

function getFileExtension(name) {
  const basename = String(name || "").split("/").pop() || "";
  const dotIndex = basename.lastIndexOf(".");
  if (dotIndex <= 0 || dotIndex === basename.length - 1) return "";
  return basename.slice(dotIndex + 1).toLowerCase();
}

function getObjectPath(bucketName, key) {
  const pathParts = String(key || "").split("/").filter(Boolean);
  return [bucketName, ...pathParts].filter(Boolean).join(" / ");
}

function getContentType(item) {
  return item.content_type || item.contentType || "binary/octet-stream";
}

function getMetadataEntries(item) {
  const metadata = item.metadata && typeof item.metadata === "object" ? item.metadata : {};
  return Object.entries(metadata).filter(([, value]) => value !== undefined && value !== null && value !== "");
}

function getTagEntries(item) {
  const tags = item.tags && typeof item.tags === "object" ? item.tags : {};
  return Object.entries(tags).filter(([, value]) => value !== undefined && value !== null && value !== "");
}

function getShareExpirySeconds(days, hours, minutes) {
  return Math.max(60, Number(days) * 86400 + Number(hours) * 3600 + Number(minutes) * 60);
}

function formatShareExpiryTime(expiresAt) {
  if (!expiresAt) return "";
  return new Intl.DateTimeFormat("en-US", {
    month: "2-digit",
    day: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZoneName: "short",
  }).format(new Date(expiresAt));
}

function getDateTimeLocalValue(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function FileTypeIcon({ name }) {
  const extension = getFileExtension(name);
  const style = defaultStyles[extension] || {};

  return (
    <span className="file-type-icon" aria-hidden="true">
      <FileIcon extension={extension} {...style} />
    </span>
  );
}

function WaveCanvas() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas.getContext("2d");
    let frame = 0;
    let animationId;

    const resize = () => {
      const { width, height } = canvas.getBoundingClientRect();
      const scale = window.devicePixelRatio || 1;
      canvas.width = Math.floor(width * scale);
      canvas.height = Math.floor(height * scale);
      context.setTransform(scale, 0, 0, scale, 0, 0);
    };

    const draw = () => {
      const { width, height } = canvas.getBoundingClientRect();
      context.clearRect(0, 0, width, height);

      const gradient = context.createLinearGradient(0, 0, width, 0);
      gradient.addColorStop(0, "rgba(105, 185, 255, 0.08)");
      gradient.addColorStop(0.5, "rgba(196, 235, 255, 0.9)");
      gradient.addColorStop(1, "rgba(81, 173, 232, 0.2)");

      context.lineWidth = 1;
      context.shadowBlur = 12;
      context.shadowColor = "rgba(102, 193, 255, 0.45)";

      for (let line = 0; line < 34; line += 1) {
        const offset = line - 17;
        context.beginPath();
        context.strokeStyle = gradient;

        for (let x = -20; x <= width + 20; x += 10) {
          const progress = x / width;
          const wave =
            Math.sin(progress * 9 + frame * 0.018 + offset * 0.08) * 66 +
            Math.sin(progress * 17 - frame * 0.011 + offset * 0.12) * 24;
          const taper = Math.sin(Math.PI * Math.min(1, Math.max(0, progress)));
          const y = height * 0.6 + wave * taper + offset * 5.8;
          if (x === -20) context.moveTo(x, y);
          else context.lineTo(x, y);
        }

        context.stroke();
      }

      context.shadowBlur = 0;
      context.fillStyle = "rgba(198, 232, 255, 0.75)";
      for (let i = 0; i < 48; i += 1) {
        const x = ((i * 89 + frame * (0.18 + (i % 5) * 0.03)) % (width + 160)) - 80;
        const y = height * 0.6 + Math.sin(i * 1.7 + frame * 0.02) * 150;
        const alpha = 0.2 + ((i % 7) / 10);
        context.globalAlpha = alpha;
        context.beginPath();
        context.arc(x, y, 1.25, 0, Math.PI * 2);
        context.fill();
      }
      context.globalAlpha = 1;

      frame += 1;
      animationId = requestAnimationFrame(draw);
    };

    resize();
    draw();
    window.addEventListener("resize", resize);
    return () => {
      cancelAnimationFrame(animationId);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return <canvas className="wave-canvas" ref={canvasRef} aria-hidden="true" />;
}

function AdminPanel({
  currentUser,
  users,
  groups,
  grants,
  assignableUsers,
  grantGroups,
  meta,
  filters,
  setFilters,
  buckets,
  newUser,
  setNewUser,
  newGrant,
  setNewGrant,
  isLoading,
  onCreateUser,
  onUpdateUser,
  onDeactivateUser,
  onCreateGroup,
  onUpdateGroup,
  onEditGroup,
  onCancelEditGroup,
  onDeleteGroup,
  onCreateGrant,
  onDeleteGrant,
  onRefresh,
  editingGroup,
}) {
  const [activeAdminTab, setActiveAdminTab] = useState("users");
  const [visibleAdminPasswords, setVisibleAdminPasswords] = useState({});
  const grantTargetUsers = assignableUsers.filter((user) => user.role === "editor" || user.role === "viewer");
  const canManageAdmins = Boolean(currentUser?.permissions?.can_manage_admins);
  const selectedGrantBuckets = Array.isArray(newGrant.buckets) ? newGrant.buckets : [];
  const areAllGrantBucketsSelected = buckets.length > 0 && buckets.every((bucket) => selectedGrantBuckets.includes(bucket.name));
  const adminTabs = [
    { id: "users", label: "Users", count: meta.users.count },
    { id: "groups", label: "Groups", count: meta.groups.count },
    { id: "grants", label: "Grants", count: meta.grants.count },
  ];

  function applyAdminFilter(section, patch) {
    const nextFilters = {
      ...filters,
      [section]: {
        ...filters[section],
        ...patch,
        page: patch.page || 1,
      },
    };
    setFilters(nextFilters);
    onRefresh(nextFilters);
  }

  function changeAdminPage(section, page) {
    applyAdminFilter(section, { page });
  }

  function renderAdminPager(section) {
    const pageMeta = meta[section];
    return (
      <div className="admin-pager">
        <span>{pageMeta.count.toLocaleString()} records</span>
        <select
          value={filters[section].page_size}
          onChange={(event) => applyAdminFilter(section, { page_size: Number(event.target.value) })}
        >
          <option value={25}>25</option>
          <option value={50}>50</option>
          <option value={100}>100</option>
        </select>
        <button type="button" disabled={pageMeta.page <= 1 || isLoading} onClick={() => changeAdminPage(section, pageMeta.page - 1)}>
          Previous
        </button>
        <span>Page {pageMeta.page} / {pageMeta.total_pages}</span>
        <button type="button" disabled={pageMeta.page >= pageMeta.total_pages || isLoading} onClick={() => changeAdminPage(section, pageMeta.page + 1)}>
          Next
        </button>
      </div>
    );
  }

  function toggleGrantBucket(bucketName) {
    setNewGrant((grant) => {
      const current = Array.isArray(grant.buckets) ? grant.buckets : [];
      return {
        ...grant,
        buckets: current.includes(bucketName)
          ? current.filter((name) => name !== bucketName)
          : [...current, bucketName],
      };
    });
  }

  function toggleAllGrantBuckets() {
    setNewGrant((grant) => ({
      ...grant,
      buckets: areAllGrantBucketsSelected ? [] : buckets.map((bucket) => bucket.name),
    }));
  }

  return (
    <section className="admin-panel" aria-label="Admin management">
      <header className="admin-header">
        <div>
          <h2><Shield size={26} /> Admin</h2>
          <p>Search, filter, and manage records in paged tables.</p>
        </div>
        <button type="button" title="Refresh admin data" onClick={() => onRefresh()}>
          Refresh <RefreshCw size={18} />
        </button>
      </header>

      <div className="admin-tabs" role="tablist" aria-label="Admin sections">
        {adminTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={activeAdminTab === tab.id ? "active" : ""}
            onClick={() => setActiveAdminTab(tab.id)}
          >
            {tab.label} <span>{tab.count.toLocaleString()}</span>
          </button>
        ))}
      </div>

      <div className="admin-grid">
        {activeAdminTab === "users" ? <section className="admin-section">
          <h3>Users</h3>
          <div className="admin-toolbar">
            <input
              placeholder="Search users"
              value={filters.users.q}
              onChange={(event) => setFilters((items) => ({ ...items, users: { ...items.users, q: event.target.value } }))}
            />
            <select value={filters.users.role} onChange={(event) => applyAdminFilter("users", { role: event.target.value })}>
              <option value="">All roles</option>
              <option value="viewer">Viewer</option>
              <option value="editor">Editor</option>
              <option value="admin">Admin</option>
              {canManageAdmins ? <option value="superuser">Superuser</option> : null}
            </select>
            <select value={filters.users.is_active} onChange={(event) => applyAdminFilter("users", { is_active: event.target.value })}>
              <option value="">Any status</option>
              <option value="true">Active</option>
              <option value="false">Inactive</option>
            </select>
            <button type="button" onClick={() => applyAdminFilter("users", { q: filters.users.q })}>Search</button>
          </div>
          <form className="admin-form" onSubmit={onCreateUser}>
            <input
              required
              placeholder="Username"
              value={newUser.username}
              onChange={(event) => setNewUser((user) => ({ ...user, username: event.target.value }))}
            />
            <input
              required
              minLength={8}
              type="password"
              placeholder="Password"
              value={newUser.password}
              onChange={(event) => setNewUser((user) => ({ ...user, password: event.target.value }))}
            />
            <select
              value={newUser.role}
              onChange={(event) => setNewUser((user) => ({ ...user, role: event.target.value }))}
            >
              <option value="viewer">Viewer</option>
              <option value="editor">Editor</option>
              {canManageAdmins ? <option value="admin">Admin</option> : null}
            </select>
            <button className="primary" type="submit">Create User</button>
          </form>

          <div className="admin-table">
            <div className="admin-row admin-row-head">
              <span>User</span>
              <span>Role</span>
              <span>Active</span>
              <span>Actions</span>
            </div>
            {isLoading ? <p className="admin-empty">Loading...</p> : null}
            {users.map((user) => (
              <form className="admin-row" key={user.id} onSubmit={(event) => onUpdateUser(event, user.id)}>
                <input name="username" defaultValue={user.username} aria-label={`${user.username} username`} />
                <select name="role" defaultValue={user.role} disabled={user.role === "superuser"}>
                  {user.role === "superuser" ? <option value="superuser">Superuser</option> : null}
                  <option value="viewer">Viewer</option>
                  <option value="editor">Editor</option>
                  {canManageAdmins || user.role === "admin" ? <option value="admin">Admin</option> : null}
                </select>
                <label className="admin-check">
                  <input name="is_active" type="checkbox" defaultChecked={user.is_active} />
                  Active
                </label>
                <div className="admin-row-actions">
                  <label className="admin-password-cell">
                    <input
                      name="password"
                      minLength={8}
                      type={visibleAdminPasswords[user.id] ? "text" : "password"}
                      placeholder="New password"
                      onChange={(event) => {
                        if (!event.target.value) {
                          setVisibleAdminPasswords((items) => ({ ...items, [user.id]: false }));
                        }
                      }}
                    />
                    <button
                      type="button"
                      aria-label={visibleAdminPasswords[user.id] ? "Hide password" : "Show password"}
                      title={visibleAdminPasswords[user.id] ? "Hide password" : "Show password"}
                      onClick={() => setVisibleAdminPasswords((items) => ({ ...items, [user.id]: !items[user.id] }))}
                    >
                      {visibleAdminPasswords[user.id] ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </label>
                  <button type="submit" title={`Save ${user.username}`}>Save</button>
                  <button
                    type="button"
                    title={`Deactivate ${user.username}`}
                    disabled={!user.is_active || user.role === "superuser"}
                    onClick={() => onDeactivateUser(user)}
                  >
                    Disable
                  </button>
                </div>
              </form>
            ))}
          </div>
          {renderAdminPager("users")}
        </section> : null}

        {activeAdminTab === "groups" ? <section className="admin-section">
          <h3>Groups</h3>
          <div className="admin-toolbar">
            <input
              placeholder="Search groups or members"
              value={filters.groups.q}
              onChange={(event) => setFilters((items) => ({ ...items, groups: { ...items.groups, q: event.target.value } }))}
            />
            <button type="button" onClick={() => applyAdminFilter("groups", { q: filters.groups.q })}>Search</button>
          </div>
          <form className="admin-form group-create-form" onSubmit={onCreateGroup}>
            <input required name="name" placeholder="Group name" />
            <fieldset className="bucket-multi-field user-multi-field">
              <legend>Members</legend>
              <div className="bucket-multi-list">
                {assignableUsers
                  .filter((user) => user.role === "editor" || user.role === "viewer")
                  .map((user) => (
                    <label key={user.id}>
                      <input name="users" type="checkbox" value={user.id} />
                      {user.username}
                    </label>
                  ))}
              </div>
            </fieldset>
            <button className="primary" type="submit">Create Group</button>
          </form>

          <div className="admin-table groups-table">
            <div className="admin-row admin-row-head">
              <span>Group</span>
              <span>Members</span>
              <span>Actions</span>
            </div>
            {groups.length ? groups.map((group) => (
              editingGroup?.id === group.id ? (
                <form className="admin-row" key={group.id} onSubmit={(event) => onUpdateGroup(event, group.id)}>
                  <input name="name" defaultValue={editingGroup.name} aria-label={`${group.name} group name`} />
                  <fieldset className="bucket-multi-field user-multi-field">
                    <legend>Members</legend>
                    <div className="bucket-multi-list">
                      {assignableUsers.map((user) => (
                        <label key={user.id}>
                          <input
                            name="users"
                            type="checkbox"
                            value={user.id}
                            defaultChecked={(editingGroup.user_details || []).some((member) => member.id === user.id)}
                          />
                          {user.username}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                  <div className="admin-row-actions">
                    <button type="submit" title={`Save ${group.name}`}>Save</button>
                    <button type="button" title="Cancel edit" onClick={onCancelEditGroup}>Cancel</button>
                  </div>
                </form>
              ) : (
                <div className="admin-row" key={group.id}>
                  <span>{group.name}</span>
                  <span>
                    {(group.member_count ?? (group.user_details || []).length).toLocaleString()} member{(group.member_count ?? (group.user_details || []).length) === 1 ? "" : "s"}
                    {(group.member_preview || []).length ? ` - ${group.member_preview.map((user) => user.username).join(", ")}` : ""}
                  </span>
                  <div className="admin-row-actions">
                    <button type="button" title={`Edit ${group.name}`} onClick={() => onEditGroup(group)}>
                      Edit
                    </button>
                    <button type="button" title={`Delete ${group.name}`} onClick={() => onDeleteGroup(group)}>
                      Delete
                    </button>
                  </div>
                </div>
              )
            )) : <p className="admin-empty">No groups yet.</p>}
          </div>
          {renderAdminPager("groups")}
        </section> : null}

        {activeAdminTab === "grants" ? <section className="admin-section">
          <h3>Visibility Grants</h3>
          <div className="admin-toolbar grant-toolbar">
            <input
              placeholder="Search target, bucket, prefix"
              value={filters.grants.q}
              onChange={(event) => setFilters((items) => ({ ...items, grants: { ...items.grants, q: event.target.value } }))}
            />
            <select value={filters.grants.target_type} onChange={(event) => applyAdminFilter("grants", { target_type: event.target.value })}>
              <option value="">Any target</option>
              <option value="role">Role</option>
              <option value="user">User</option>
              <option value="group">Group</option>
            </select>
            <select value={filters.grants.bucket} onChange={(event) => applyAdminFilter("grants", { bucket: event.target.value })}>
              <option value="">Any bucket</option>
              {buckets.map((bucket) => <option key={bucket.name} value={bucket.name}>{bucket.name}</option>)}
            </select>
            <select value={filters.grants.access} onChange={(event) => applyAdminFilter("grants", { access: event.target.value })}>
              <option value="">Any access</option>
              <option value="read">Read</option>
              <option value="write">Write</option>
            </select>
            <button type="button" onClick={() => applyAdminFilter("grants", { q: filters.grants.q })}>Search</button>
          </div>
          <form className="admin-form grant-form" onSubmit={onCreateGrant}>
            <select
              value={newGrant.target_type}
              onChange={(event) => setNewGrant((grant) => ({ ...grant, target_type: event.target.value }))}
            >
              <option value="role">Role</option>
              <option value="user">User</option>
              <option value="group">Group</option>
            </select>
            {newGrant.target_type === "role" ? (
              <select
                value={newGrant.role}
                onChange={(event) => setNewGrant((grant) => ({ ...grant, role: event.target.value }))}
              >
                <option value="viewer">Viewer</option>
                <option value="editor">Editor</option>
              </select>
            ) : newGrant.target_type === "user" ? (
              <select
                required
                value={newGrant.user}
                onChange={(event) => setNewGrant((grant) => ({ ...grant, user: event.target.value }))}
              >
                <option value="">Choose user</option>
                {grantTargetUsers.map((user) => (
                  <option key={user.id} value={user.id}>{user.username}</option>
                ))}
              </select>
            ) : (
              <select
                required
                value={newGrant.group}
                onChange={(event) => setNewGrant((grant) => ({ ...grant, group: event.target.value }))}
              >
                <option value="">Choose group</option>
                {grantGroups.map((group) => (
                  <option key={group.id} value={group.id}>{group.name}</option>
                ))}
              </select>
            )}
            <fieldset className="bucket-multi-field">
              <legend>Bucket</legend>
              <label className="bucket-multi-all">
                <input
                  type="checkbox"
                  checked={areAllGrantBucketsSelected}
                  onChange={toggleAllGrantBuckets}
                />
                All buckets
              </label>
              <div className="bucket-multi-list">
                {buckets.map((bucket) => (
                  <label key={bucket.name}>
                    <input
                      type="checkbox"
                      checked={selectedGrantBuckets.includes(bucket.name)}
                      onChange={() => toggleGrantBucket(bucket.name)}
                    />
                    {bucket.name}
                  </label>
                ))}
              </div>
            </fieldset>
            <input
              placeholder="Prefix, blank = whole bucket"
              value={newGrant.prefix}
              onChange={(event) => setNewGrant((grant) => ({ ...grant, prefix: event.target.value }))}
            />
            <select
              value={newGrant.access}
              onChange={(event) => setNewGrant((grant) => ({ ...grant, access: event.target.value }))}
            >
              <option value="read">Read</option>
              <option value="write">Write</option>
            </select>
            <button className="primary" type="submit" disabled={!selectedGrantBuckets.length}>Create Grant</button>
          </form>

          <div className="admin-table grants-table">
            <div className="admin-row admin-row-head">
              <span>Target</span>
              <span>Bucket / Prefix</span>
              <span>Access</span>
              <span>Actions</span>
            </div>
            {grants.length ? grants.map((grant) => (
              <div className="admin-row" key={grant.id}>
                <span className="grant-target">
                  <span className={`grant-target-type ${grant.target_type}`}>
                    {grant.target_type}
                  </span>
                  <strong title={
                    grant.target_type === "role"
                      ? grant.role
                      : grant.target_type === "group"
                        ? grant.group_name || grant.group
                        : grant.username || grant.user
                  }>
                    {grant.target_type === "role"
                      ? grant.role
                      : grant.target_type === "group"
                        ? grant.group_name || grant.group
                        : grant.username || grant.user}
                  </strong>
                </span>
                <span className="grant-scope">
                  <strong title={grant.bucket || "All buckets"}>{grant.bucket || "All buckets"}</strong>
                  <span title={grant.prefix || "Whole bucket"}>
                    {grant.prefix ? `/${grant.prefix}` : "Whole bucket"}
                  </span>
                </span>
                <span className={`access-badge ${grant.access}`}>
                  {grant.access}
                </span>
                <div className="admin-row-actions">
                  <button className="danger-quiet" type="button" title="Delete grant" onClick={() => onDeleteGrant(grant)}>
                    Delete
                  </button>
                </div>
              </div>
            )) : <p className="admin-empty">No visibility grants yet.</p>}
          </div>
          {renderAdminPager("grants")}
        </section> : null}
      </div>
    </section>
  );
}

function App() {
  const [isAuthenticated, setAuthenticated] = useState(false);
  const [isCheckingSession, setCheckingSession] = useState(true);
  const [route, setRoute] = useState(getRoute);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [status, setStatus] = useState("");
  const [isSubmitting, setSubmitting] = useState(false);

  const canSubmit = username.trim() && password.length >= 8 && !isSubmitting && !isCheckingSession;

  useEffect(() => {
    const handleRouteChange = () => setRoute(getRoute());
    window.addEventListener("popstate", handleRouteChange);
    return () => window.removeEventListener("popstate", handleRouteChange);
  }, []);

  useEffect(() => {
    let isMounted = true;
    getMe()
      .then(() => {
        if (!isMounted) return;
        setAuthenticated(true);
      })
      .catch(() => {
        if (!isMounted) return;
        setAuthenticated(false);
      })
      .finally(() => {
        if (!isMounted) return;
        setCheckingSession(false);
      });
    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (isCheckingSession) return;
    if (!isAuthenticated && route.page !== "login") pushRoute("/login");
    if (isAuthenticated && route.page === "login") pushRoute("/browser");
  }, [isAuthenticated, isCheckingSession, route.page]);

  useEffect(() => {
    document.documentElement.style.setProperty("--app-scale", "0.75");
    localStorage.removeItem("appScale");
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    setStatus("");

    try {
      await login(username.trim(), password);
      setAuthenticated(true);
      setStatus("");
      pushRoute("/browser");
    } catch (error) {
      setStatus(error.message);
    } finally {
      setSubmitting(false);
    }
  }

  function handleAuthExpired() {
    setAuthenticated(false);
    setPassword("");
    setStatus("Session expired. Login again.");
    pushRoute("/login");
  }

  async function handleSignOut() {
    try {
      await logout();
    } catch (_error) {
      // Session may already be gone; local state still needs clearing.
    }
    setAuthenticated(false);
    setPassword("");
    pushRoute("/login");
  }

  if (!isCheckingSession && isAuthenticated) {
    return (
      <ObjectBrowser
        routeBucket={route.bucket}
        token=""
        onAuthExpired={handleAuthExpired}
        onSelectBucket={(bucket) => pushRoute(`/browser/${encodeURIComponent(bucket)}`)}
        onSignOut={handleSignOut}
      />
    );
  }

  return (
    <main className="auth-shell auth-login-shell">
      <section className="auth-copy" aria-label="Product overview">
        <div className="copy-content">
          <h1>High-Performance Object Store</h1>
          <p>
            MinIO is a cloud-native object store built to run on any infrastructure - public,
            private or edge clouds. Primary use cases include data lakes, databases, AI/ML,
            SaaS applications and fast backup & recovery.
          </p>
        </div>
        <WaveCanvas />
      </section>

      <section className="auth-panel" aria-label="Authentication">
        <div className="brand-lockup">
          <div className="brand-minio">MINIO</div>
          <div className="brand-title">OBJECT <span>STORE</span></div>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="input-row">
            <User size={18} aria-hidden="true" />
            <input
              autoComplete="username"
              placeholder="Username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </label>

          <label className="input-row">
            <LockKeyhole size={18} aria-hidden="true" />
            <input
              autoComplete="current-password"
              placeholder="Password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <button
              className="icon-button"
              type="button"
              aria-label={showPassword ? "Hide password" : "Show password"}
              title={showPassword ? "Hide password" : "Show password"}
              onClick={() => setShowPassword((value) => !value)}
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </label>

          <button
            className="submit-button"
            disabled={!canSubmit}
            title="Login to object browser"
          >
            {isCheckingSession ? "Checking..." : isSubmitting ? "Working..." : "Login"}
          </button>

          {status ? <p className="form-status">{status}</p> : null}
        </form>

        <nav className="auth-links" aria-label="Resources">
          <a href="https://min.io/docs/minio/linux/index.html">Documentation</a>
          <a href="https://github.com/minio/minio">GitHub</a>
          <a href="https://min.io/product/support">Support</a>
          <a href="https://min.io/download">Download</a>
        </nav>
      </section>
    </main>
  );
}

function ObjectBrowser({ routeBucket, token, onAuthExpired, onSelectBucket, onSignOut }) {
  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);
  const [isModalOpen, setModalOpen] = useState(false);
  const [isPathModalOpen, setPathModalOpen] = useState(false);
  const [isPreviewModalOpen, setPreviewModalOpen] = useState(false);
  const [isRewindModalOpen, setRewindModalOpen] = useState(false);
  const [isShareModalOpen, setShareModalOpen] = useState(false);
  const [isTagsModalOpen, setTagsModalOpen] = useState(false);
  const [isTransfersOpen, setTransfersOpen] = useState(false);
  const [isUploadMenuOpen, setUploadMenuOpen] = useState(false);
  const [bucketName, setBucketName] = useState("");
  const [bucketGroupId, setBucketGroupId] = useState("");
  const [newFolderPath, setNewFolderPath] = useState("");
  const [shareDays, setShareDays] = useState(0);
  const [shareHours, setShareHours] = useState(12);
  const [shareMinutes, setShareMinutes] = useState(0);
  const [shareUrl, setShareUrl] = useState("");
  const [shareExpiresAt, setShareExpiresAt] = useState("");
  const [rewindDate, setRewindDate] = useState(() => {
    const startOfDay = new Date();
    startOfDay.setHours(0, 0, 0, 0);
    return getDateTimeLocalValue(startOfDay);
  });
  const [isRewindEnabled, setRewindEnabled] = useState(true);
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewTarget, setPreviewTarget] = useState(null);
  const [previewVersionId, setPreviewVersionId] = useState("");
  const [shareTarget, setShareTarget] = useState(null);
  const [shareVersionId, setShareVersionId] = useState("");
  const [tagKey, setTagKey] = useState("");
  const [tagLabel, setTagLabel] = useState("");
  const [currentTags, setCurrentTags] = useState({});
  const [buckets, setBuckets] = useState([]);
  const [selectedBucket, setSelectedBucket] = useState("");
  const [objects, setObjects] = useState([]);
  const [nextContinuationToken, setNextContinuationToken] = useState("");
  const [isObjectListTruncated, setObjectListTruncated] = useState(false);
  const [rewindObjects, setRewindObjects] = useState([]);
  const [isRewindMode, setRewindMode] = useState(false);
  const [rewindAppliedAt, setRewindAppliedAt] = useState("");
  const [versionItems, setVersionItems] = useState([]);
  const [isVersionsMode, setVersionsMode] = useState(false);
  const [isVersionMultiSelect, setVersionMultiSelect] = useState(false);
  const [selectedVersionIds, setSelectedVersionIds] = useState([]);
  const [versionSort, setVersionSort] = useState("date");
  const [currentPrefix, setCurrentPrefix] = useState("");
  const [selectedObject, setSelectedObject] = useState(null);
  const [selectedEntryKeys, setSelectedEntryKeys] = useState([]);
  const [pendingFolders, setPendingFolders] = useState([]);
  const [transfers, setTransfers] = useState([]);
  const [bucketFilter, setBucketFilter] = useState("");
  const [objectFilter, setObjectFilter] = useState("");
  const [status, setStatus] = useState("");
  const [isPathCopied, setPathCopied] = useState(false);
  const [isCreating, setCreating] = useState(false);
  const [isLoading, setLoading] = useState(false);
  const [isUploading, setUploading] = useState(false);
  const [isCreatingShare, setCreatingShare] = useState(false);
  const [isLoadingPreview, setLoadingPreview] = useState(false);
  const [isSavingTags, setSavingTags] = useState(false);
  const [isLoadingVersions, setLoadingVersions] = useState(false);
  const [isLoadingRewind, setLoadingRewind] = useState(false);
  const [currentUser, setCurrentUser] = useState(null);
  const [activeView, setActiveView] = useState("browser");
  const [adminUsers, setAdminUsers] = useState([]);
  const [adminAssignableUsers, setAdminAssignableUsers] = useState([]);
  const [accessGroups, setAccessGroups] = useState([]);
  const [grantGroups, setGrantGroups] = useState([]);
  const [visibilityGrants, setVisibilityGrants] = useState([]);
  const [editingGroup, setEditingGroup] = useState(null);
  const [adminMeta, setAdminMeta] = useState({
    users: { count: 0, page: 1, page_size: 25, total_pages: 1 },
    groups: { count: 0, page: 1, page_size: 25, total_pages: 1 },
    grants: { count: 0, page: 1, page_size: 25, total_pages: 1 },
  });
  const [adminFilters, setAdminFilters] = useState({
    users: { q: "", role: "", is_active: "", page: 1, page_size: 25 },
    groups: { q: "", page: 1, page_size: 25 },
    grants: { q: "", target_type: "", bucket: "", access: "", page: 1, page_size: 25 },
  });
  const [newUser, setNewUser] = useState({ username: "", password: "", role: "viewer" });
  const [newGrant, setNewGrant] = useState({
    target_type: "role",
    role: "viewer",
    user: "",
    group: "",
    buckets: [],
    prefix: "",
    access: "read",
  });
  const [isAdminLoading, setAdminLoading] = useState(false);
  const [writablePrefixes, setWritablePrefixes] = useState([]);

  const normalizedName = bucketName.trim().toLowerCase();
  const normalizedFolderPath = normalizeFolderPath(newFolderPath);
  const isValidBucketName = /^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/.test(normalizedName);
  const permissions = currentUser?.permissions || {};
  const canManageUsers = Boolean(permissions.can_manage_users);
  const hasGlobalWrite = Boolean(permissions.can_write_storage);
  const canWritePrefix = (prefix = "") =>
    hasGlobalWrite ||
    writablePrefixes.some((grantPrefix) => {
      if (!grantPrefix) return true;
      return prefixMatchesKey(grantPrefix, prefix);
    });
  const canWriteKey = (key = "") => canWritePrefix(key);
  const canWriteCurrentPrefix = canWritePrefix(currentPrefix);
  const canCreate = isValidBucketName && !isCreating && hasGlobalWrite;
  const canCreatePath = normalizedFolderPath.length > 0 && canWriteCurrentPrefix;
  const filteredBuckets = buckets.filter((bucket) =>
    bucket.name.toLowerCase().includes(bucketFilter.trim().toLowerCase())
  );
  const selected = buckets.find((bucket) => bucket.name === selectedBucket);
  const activeObjects = isRewindMode ? rewindObjects : objects;
  const objectEntries = buildObjectEntries(activeObjects, currentPrefix, objectFilter, isRewindMode ? [] : pendingFolders);
  const visibleEntryKeys = objectEntries.map((item) => item.key);
  const visibleEntryKeySignature = visibleEntryKeys.join("\u0000");
  const selectedEntryCount = selectedEntryKeys.length;
  const selectedEntries = objectEntries.filter((item) => selectedEntryKeys.includes(item.key));
  const selectedFileEntries = selectedEntries.filter((item) => item.type !== "folder");
  const selectedSingleFile = selectedFileEntries.length === 1 && selectedEntries.length === 1 ? selectedFileEntries[0] : null;
  const canDeleteSelectedEntries = selectedEntries.length > 0 && selectedEntries.every((item) => {
    if (item.type !== "folder") return canWriteKey(item.key);
    return activeObjects.filter((object) => object.key.startsWith(item.key)).every((object) => canWriteKey(object.key));
  });
  const hasObjectSidePanel = Boolean(selectedObject) || selectedEntryCount > 0;
  const areAllVisibleEntriesSelected =
    visibleEntryKeys.length > 0 && visibleEntryKeys.every((key) => selectedEntryKeys.includes(key));
  const objectCount = activeObjects.length;
  const totalSize = activeObjects.reduce((sum, item) => sum + (Number(item.size) || 0), 0);
  const currentPath = currentPrefix ? `${selected?.name || ""} / ${currentPrefix.split("/").filter(Boolean).join(" / ")}` : selected?.name;
  const displayedPath = selectedObject ? getObjectPath(selected?.name || "", selectedObject.key) : currentPath;
  const displayedPathLabel = isVersionsMode && selectedObject
    ? `${selected?.name || ""} / ${selectedObject.key} - Versions`
    : displayedPath;
  const selectedMetadataEntries = selectedObject ? getMetadataEntries(selectedObject) : [];
  const selectedTagEntries = selectedObject ? getTagEntries(selectedObject) : [];
  const activeTransferCount = transfers.length;
  const sortedVersionItems = [...versionItems].sort((a, b) => {
    if (versionSort === "size") return (Number(b.size) || 0) - (Number(a.size) || 0);
    return new Date(b.last_modified || 0).getTime() - new Date(a.last_modified || 0).getTime();
  });
  const versionTotalSize = versionItems.reduce((sum, item) => sum + (Number(item.size) || 0), 0);
  const selectedVersionCount = selectedVersionIds.length;

  function closeModals() {
    setModalOpen(false);
    setPathModalOpen(false);
    setPreviewModalOpen(false);
    setRewindModalOpen(false);
    setShareModalOpen(false);
    setTagsModalOpen(false);
    setPreviewUrl("");
    setPreviewTarget(null);
    setPreviewVersionId("");
  }

  function addTransfer(item) {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setTransfers((current) => [{ id, progress: 15, status: "active", ...item }, ...current]);
    setTransfersOpen(true);
    return id;
  }

  function updateTransfer(id, updates) {
    setTransfers((current) =>
      current.map((item) => (item.id === id ? { ...item, ...updates } : item))
    );
  }

  function removeTransfer(id) {
    setTransfers((current) => current.filter((item) => item.id !== id));
  }

  async function refreshCurrentUser() {
    try {
      const data = await getMe(token);
      setCurrentUser(data);
      if (!data.permissions?.can_manage_users) setActiveView("browser");
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  function getAdminPageMeta(data, fallbackItems = []) {
    return {
      count: data.count ?? fallbackItems.length,
      page: data.page || 1,
      page_size: data.page_size || 25,
      total_pages: data.total_pages || 1,
    };
  }

  async function refreshAdminData(nextFilters = adminFilters) {
    if (!canManageUsers) return;
    setAdminLoading(true);
    try {
      const [usersData, grantsData, groupsData] = await Promise.all([
        listUsers(token, nextFilters.users),
        listVisibilityGrants(token, nextFilters.grants),
        listGroups(token, nextFilters.groups),
      ]);
      const [selectorUsersData, selectorGroupsData] = await Promise.all([
        listUsers(token, { page_size: 100 }),
        listGroups(token, { page_size: 100 }),
      ]);
      const nextUsers = usersData.results || usersData.users || [];
      const nextGrants = grantsData.results || grantsData.grants || [];
      const nextGroups = groupsData.results || groupsData.groups || [];
      setAdminUsers(nextUsers);
      setVisibilityGrants(nextGrants);
      setAccessGroups(nextGroups);
      setAdminAssignableUsers(selectorUsersData.results || selectorUsersData.users || []);
      setGrantGroups(selectorGroupsData.results || selectorGroupsData.groups || []);
      setAdminMeta({
        users: getAdminPageMeta(usersData, nextUsers),
        grants: getAdminPageMeta(grantsData, nextGrants),
        groups: getAdminPageMeta(groupsData, nextGroups),
      });
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    } finally {
      setAdminLoading(false);
    }
  }

  async function handleCreateUser(event) {
    event.preventDefault();
    setStatus("");
    try {
      const user = await createUser(token, newUser);
      setNewUser({ username: "", password: "", role: "viewer" });
      setStatus(`User "${user.username}" created.`);
      await refreshAdminData();
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  async function handleUpdateUser(event, userId) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const payload = {
      username: String(form.get("username") || "").trim(),
      role: String(form.get("role") || "viewer"),
      is_active: form.get("is_active") === "on",
    };
    const passwordValue = String(form.get("password") || "");
    if (passwordValue) payload.password = passwordValue;
    try {
      const user = await updateUser(token, userId, payload);
      if (formElement?.elements?.password) formElement.elements.password.value = "";
      setStatus(`User "${user.username}" updated.`);
      await refreshAdminData();
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  async function handleDeactivateUser(user) {
    if (!window.confirm(`Deactivate "${user.username}"?`)) return;
    try {
      await deactivateUser(token, user.id);
      setStatus(`User "${user.username}" deactivated.`);
      await refreshAdminData();
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  async function handleCreateGroup(event) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const payload = {
      name: String(form.get("name") || "").trim(),
      users: form.getAll("users").map((id) => Number(id)),
    };
    try {
      const group = await createGroup(token, payload);
      formElement?.reset();
      setStatus(`Group "${group.name}" created.`);
      await refreshAdminData();
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  async function handleUpdateGroup(event, groupId) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {
      name: String(form.get("name") || "").trim(),
      users: form.getAll("users").map((id) => Number(id)),
    };
    try {
      const group = await updateGroup(token, groupId, payload);
      setEditingGroup(null);
      setStatus(`Group "${group.name}" updated.`);
      await refreshAdminData();
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  async function handleEditGroup(group) {
    try {
      const detail = await getGroup(token, group.id);
      setEditingGroup(detail);
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  async function handleDeleteGroup(group) {
    if (!window.confirm(`Delete group "${group.name}"? Grants for this group will also be removed.`)) return;
    try {
      await deleteGroup(token, group.id);
      setEditingGroup((item) => (item?.id === group.id ? null : item));
      setStatus(`Group "${group.name}" deleted.`);
      await refreshAdminData();
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  async function handleCreateGrant(event) {
    event.preventDefault();
    const selectedBuckets = Array.isArray(newGrant.buckets) ? newGrant.buckets : [];
    if (!selectedBuckets.length) return;
    try {
      const createdGrants = [];
      for (const bucket of selectedBuckets) {
        const payload = {
          target_type: newGrant.target_type,
          role: newGrant.target_type === "role" ? newGrant.role : "",
          user: newGrant.target_type === "user" ? Number(newGrant.user) : null,
          group: newGrant.target_type === "group" ? Number(newGrant.group) : null,
          bucket,
          prefix: newGrant.prefix.trim(),
          access: newGrant.access,
        };
        createdGrants.push(await createVisibilityGrant(token, payload));
      }
      setNewGrant({
        target_type: "role",
        role: "viewer",
        user: "",
        group: "",
        buckets: [],
        prefix: "",
        access: "read",
      });
      setStatus(`Created ${createdGrants.length} visibility grant${createdGrants.length === 1 ? "" : "s"}.`);
      await refreshAdminData();
      await refreshBuckets();
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  async function handleDeleteGrant(grant) {
    if (!window.confirm("Delete this visibility grant?")) return;
    try {
      await deleteVisibilityGrant(token, grant.id);
      setStatus("Visibility grant deleted.");
      await refreshAdminData();
      await refreshBuckets();
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  useEffect(() => {
    refreshCurrentUser();
  }, []);

  useEffect(() => {
    refreshBuckets();
  }, []);

  useEffect(() => {
    if (canManageUsers) refreshAdminData();
  }, [canManageUsers]);

  useEffect(() => {
    closeModals();
    if (routeBucket) setSelectedBucket(routeBucket);
  }, [routeBucket]);

  useEffect(() => {
    if (selectedObject) return;
    setPreviewModalOpen(false);
    setShareModalOpen(false);
    setTagsModalOpen(false);
    setPreviewUrl("");
    setPreviewTarget(null);
    setPreviewVersionId("");
    setShareTarget(null);
    setShareVersionId("");
    setVersionsMode(false);
    setVersionItems([]);
    setVersionMultiSelect(false);
    setSelectedVersionIds([]);
    setSelectedEntryKeys([]);
    setRewindMode(false);
    setRewindObjects([]);
    setRewindAppliedAt("");
  }, [selectedObject]);

  useEffect(() => {
    const handleEscape = (event) => {
      if (event.key === "Escape") closeModals();
    };

    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, []);

  useEffect(() => {
    if (selectedBucket) refreshObjects(selectedBucket);
    else setObjects([]);
    if (!selectedBucket) setWritablePrefixes([]);
    setCurrentPrefix("");
    setSelectedObject(null);
    setVersionsMode(false);
    setVersionItems([]);
    setVersionMultiSelect(false);
    setSelectedVersionIds([]);
    setSelectedEntryKeys([]);
    setRewindMode(false);
    setRewindObjects([]);
    setRewindAppliedAt("");
    setPendingFolders([]);
    setNextContinuationToken("");
    setObjectListTruncated(false);
    setPathCopied(false);
  }, [selectedBucket]);

  useEffect(() => {
    if (!isPathCopied) return undefined;
    const timeoutId = window.setTimeout(() => setPathCopied(false), 1600);
    return () => window.clearTimeout(timeoutId);
  }, [isPathCopied]);

  useEffect(() => {
    setSelectedEntryKeys((keys) => keys.filter((key) => visibleEntryKeys.includes(key)));
  }, [visibleEntryKeySignature]);

  async function refreshBuckets() {
    setLoading(true);
    setStatus("");
    try {
      const data = await listBuckets(token);
      const nextBuckets = (data.buckets || []).map((bucket) => ({
        name: bucket.name,
        createdAt: bucket.created_at,
      }));
      setBuckets(nextBuckets);
      setSelectedBucket((current) => {
        if (routeBucket && nextBuckets.some((bucket) => bucket.name === routeBucket)) return routeBucket;
        if (current && nextBuckets.some((bucket) => bucket.name === current)) return current;
        return nextBuckets[0]?.name || "";
      });
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    } finally {
      setLoading(false);
    }
  }

  async function refreshObjects(bucket, { append = false, continuationToken = "" } = {}) {
    setLoading(true);
    setStatus("");
    try {
      const data = await listObjects(token, bucket, { continuationToken });
      const nextObjects = data.objects || [];
      const combinedObjects = append ? [...objects, ...nextObjects] : nextObjects;
      setObjects(combinedObjects);
      setWritablePrefixes(data.writable_prefixes || []);
      setNextContinuationToken(data.next_continuation_token || "");
      setObjectListTruncated(Boolean(data.is_truncated));
      setSelectedObject((current) => {
        if (!current) return null;
        const nextSelected = combinedObjects.find((item) => item.key === current.key);
        if (!nextSelected) return null;
        return {
          ...nextSelected,
          type: "file",
          name: current.name || getObjectDisplayName(nextSelected.key, currentPrefix),
        };
      });
      setPendingFolders((folders) =>
        folders.filter((folder) => !combinedObjects.some((item) => item.key.startsWith(folder)))
      );
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    } finally {
      setLoading(false);
    }
  }

  function loadMoreObjects() {
    if (!selected?.name || !nextContinuationToken || isRewindMode) return;
    refreshObjects(selected.name, { append: true, continuationToken: nextContinuationToken });
  }

  function clearRewindData() {
    setRewindMode(false);
    setRewindObjects([]);
    setRewindAppliedAt("");
    setSelectedEntryKeys([]);
  }

  function handleOpenRewind() {
    if (!selected) return;
    setRewindModalOpen(true);
  }

  async function handleShowRewindData() {
    if (!selected || !rewindDate || !isRewindEnabled) return;
    setLoadingRewind(true);
    setStatus("");
    try {
      const rewindTo = new Date(rewindDate).toISOString();
      const data = await rewindBucket(token, selected.name, rewindTo);
      const nextObjects = data.objects || [];
      setRewindObjects(nextObjects);
      setRewindAppliedAt(data.rewind_to || rewindTo);
      setRewindMode(true);
      setSelectedObject(null);
      setVersionsMode(false);
      setVersionItems([]);
      setSelectedEntryKeys([]);
      setRewindModalOpen(false);
      setStatus(`Showing rewind data for "${selected.name}" at ${formatCreatedAt(data.rewind_to || rewindTo)}.`);
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    } finally {
      setLoadingRewind(false);
    }
  }

  async function handleCreateBucket(event) {
    event.preventDefault();
    if (!hasGlobalWrite) return;
    setCreating(true);
    setStatus("");

    try {
      const bucket = await createBucket(token, normalizedName, {
        group_id: bucketGroupId ? Number(bucketGroupId) : null,
        open_to_all: !bucketGroupId,
      });
      const created = {
        name: bucket.name,
        createdAt: new Date().toISOString(),
      };
      setBuckets((items) => [...items, created]);
      setSelectedBucket(bucket.name);
      onSelectBucket(bucket.name);
      setBucketName("");
      setBucketGroupId("");
      setModalOpen(false);
      setStatus(`Bucket "${bucket.name}" created.`);
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    } finally {
      setCreating(false);
    }
  }

  async function uploadFiles(files) {
    if (!selected || files.length === 0 || !canWriteCurrentPrefix) return;
    setUploading(true);
    setStatus(`Uploading ${files.length} file${files.length === 1 ? "" : "s"}...`);

    try {
      for (const file of files) {
        const key = `${currentPrefix}${file.webkitRelativePath || file.name}`;
        const transferId = addTransfer({
          bucket: selected.name,
          name: file.name,
          type: "upload",
        });
        await uploadObject(token, selected.name, file, key);
        updateTransfer(transferId, { progress: 100, status: "done" });
      }
      setStatus(`Uploaded ${files.length} file${files.length === 1 ? "" : "s"}.`);
      await refreshObjects(selected.name);
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
      if (folderInputRef.current) folderInputRef.current.value = "";
    }
  }

  function handleUploadFileChange(event) {
    uploadFiles(Array.from(event.target.files || []));
  }

  function handleUploadFolderChange(event) {
    uploadFiles(Array.from(event.target.files || []));
  }

  function handleCreatePath(event) {
    event.preventDefault();
    if (!canCreatePath) return;

    const folderKey = `${currentPrefix}${normalizedFolderPath}/`;
    setPendingFolders((folders) => (folders.includes(folderKey) ? folders : [...folders, folderKey]));
    setNewFolderPath("");
    setPathModalOpen(false);
    setStatus(`Path "${folderKey}" ready. Upload a file into it to persist it.`);
  }

  async function handleCopyPath() {
    if (!selected) return;

    const path = selectedObject ? `${selected.name}/${selectedObject.key}` : currentPrefix ? `${selected.name}/${currentPrefix}` : selected.name;

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(path);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = path;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        document.body.removeChild(textarea);
      }
      setPathCopied(true);
      setStatus(`Copied "${path}" to clipboard.`);
    } catch (error) {
      setPathCopied(false);
      setStatus("Could not copy path to clipboard.");
    }
  }

  async function handleDownloadObject(targetObject = selectedObject, versionId = "") {
    if (!selected || !targetObject) return;
    const effectiveVersionId = versionId || targetObject.version_id || "";
    const transferId = addTransfer({
      bucket: selected.name,
      name: targetObject.name,
      type: "download",
    });
    try {
      const blob = await downloadObject(token, selected.name, targetObject.key, effectiveVersionId);
      updateTransfer(transferId, { progress: 80 });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = targetObject.name;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      updateTransfer(transferId, { progress: 100, status: "done" });
      setStatus(`Downloading "${targetObject.name}".`);
    } catch (error) {
      updateTransfer(transferId, { progress: 100, status: "error" });
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  async function createShareLink() {
    const targetObject = shareTarget || selectedObject;
    if (!selected || !targetObject) return;
    const expiresIn = getShareExpirySeconds(shareDays, shareHours, shareMinutes);
    setCreatingShare(true);
    try {
      const data = await shareObject(token, selected.name, targetObject.key, expiresIn, {
        versionId: shareVersionId || targetObject.version_id || "",
      });
      const expiresAt = new Date(Date.now() + data.expires_in * 1000).toISOString();
      setShareUrl(data.url);
      setShareExpiresAt(expiresAt);
      setStatus(`Share link created for "${targetObject.name}".`);
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    } finally {
      setCreatingShare(false);
    }
  }

  async function handleOpenPreview(targetObject = selectedObject, versionId = "") {
    if (!selected || !targetObject) return;
    const effectiveVersionId = versionId || targetObject.version_id || "";
    setPreviewTarget(targetObject);
    setPreviewVersionId(effectiveVersionId);
    setPreviewModalOpen(true);
    setPreviewUrl("");
    setLoadingPreview(true);
    try {
      const data = await shareObject(token, selected.name, targetObject.key, 12 * 60 * 60, {
        preview: true,
        versionId: effectiveVersionId,
      });
      setPreviewUrl(data.url);
      setStatus(`Preview opened for "${targetObject.name}".`);
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
      setPreviewModalOpen(false);
    } finally {
      setLoadingPreview(false);
    }
  }

  async function handleOpenShare(targetObject = selectedObject, versionId = "") {
    setShareTarget(targetObject);
    setShareVersionId(versionId || targetObject?.version_id || "");
    setShareUrl("");
    setShareExpiresAt("");
    setShareDays(0);
    setShareHours(12);
    setShareMinutes(0);
    setShareModalOpen(true);
  }

  async function handleCopyShareUrl() {
    if (!shareUrl) return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(shareUrl);
        setStatus(`Share link copied for "${(shareTarget || selectedObject)?.name}".`);
      } else {
        setStatus(`Share link: ${shareUrl}`);
      }
    } catch (error) {
      setStatus("Could not copy share link.");
    }
  }

  async function handleOpenTags() {
    if (!selected || !selectedObject || !canWriteKey(selectedObject.key)) return;
    try {
      const data = await getObjectTags(token, selected.name, selectedObject.key);
      setCurrentTags(data.tags || {});
      setTagKey("");
      setTagLabel("");
      setTagsModalOpen(true);
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  async function handleSaveTags(event) {
    event.preventDefault();
    if (!selected || !selectedObject || !canWriteKey(selectedObject.key)) return;
    const nextKey = tagKey.trim();
    const nextLabel = tagLabel.trim();
    if (!nextKey || !nextLabel) return;

    setSavingTags(true);
    try {
      const tags = { ...currentTags, [nextKey]: nextLabel };
      const data = await saveObjectTags(token, selected.name, selectedObject.key, tags);
      setCurrentTags(data.tags || {});
      setObjects((items) =>
        items.map((item) => (item.key === selectedObject.key ? { ...item, tags: data.tags } : item))
      );
      setSelectedObject((item) => (item ? { ...item, tags: data.tags } : item));
      setTagKey("");
      setTagLabel("");
      setStatus(`Tags saved for "${selectedObject.name}".`);
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    } finally {
      setSavingTags(false);
    }
  }

  function handleClearTagForm() {
    setTagKey("");
    setTagLabel("");
  }

  async function handleRemoveTag(tagName) {
    if (!selected || !selectedObject || !canWriteKey(selectedObject.key)) return;
    const { [tagName]: _removed, ...nextTags } = currentTags;
    setSavingTags(true);
    try {
      const data = await saveObjectTags(token, selected.name, selectedObject.key, nextTags);
      setCurrentTags(data.tags || {});
      setObjects((items) =>
        items.map((item) => (item.key === selectedObject.key ? { ...item, tags: data.tags } : item))
      );
      setSelectedObject((item) => (item ? { ...item, tags: data.tags } : item));
      setStatus(`Removed tag "${tagName}" from "${selectedObject.name}".`);
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    } finally {
      setSavingTags(false);
    }
  }

  async function handleDisplayVersions() {
    if (!selected || !selectedObject) return;
    setLoadingVersions(true);
    try {
      const data = await listObjectVersions(token, selected.name, selectedObject.key);
      const nextVersions = (data.versions || []).map((item, index) => ({
        ...item,
        ordinal: (data.versions || []).length - index,
      }));
      setVersionItems(nextVersions);
      setVersionsMode(true);
      setVersionMultiSelect(false);
      setSelectedVersionIds([]);
      setStatus(
        nextVersions.length
          ? `${nextVersions.length} version${nextVersions.length === 1 ? "" : "s"} found for "${selectedObject.name}".`
          : `No object versions found for "${selectedObject.name}".`
      );
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    } finally {
      setLoadingVersions(false);
    }
  }

  function handleHideVersions() {
    setVersionsMode(false);
    setVersionItems([]);
    setVersionMultiSelect(false);
    setSelectedVersionIds([]);
  }

  function handlePathBack() {
    if (isVersionsMode) {
      handleHideVersions();
      return;
    }
    if (selectedObject) {
      setSelectedObject(null);
      return;
    }
    setSelectedEntryKeys([]);
    setCurrentPrefix((prefix) => getParentPrefix(prefix));
  }

  function toggleEntrySelection(key) {
    setSelectedEntryKeys((keys) =>
      keys.includes(key) ? keys.filter((item) => item !== key) : [...keys, key]
    );
  }

  function toggleAllVisibleEntries() {
    setSelectedEntryKeys((keys) => {
      if (areAllVisibleEntriesSelected) {
        return keys.filter((key) => !visibleEntryKeys.includes(key));
      }
      return Array.from(new Set([...keys, ...visibleEntryKeys]));
    });
  }

  function openObjectEntry(item) {
    setSelectedEntryKeys([]);
    if (item.type === "folder") {
      setSelectedObject(null);
      setVersionsMode(false);
      setVersionItems([]);
      setCurrentPrefix(item.key);
      return;
    }
    setSelectedObject(item);
    setVersionsMode(false);
    setVersionItems([]);
  }

  async function handleDeleteSelectedEntries() {
    if (!selected || selectedEntryKeys.length === 0 || !canDeleteSelectedEntries) return;
    const count = selectedEntries.length;
    if (!window.confirm(`Delete ${count} selected item${count === 1 ? "" : "s"}? Folder selections delete all objects inside.`)) return;

    const objectKeys = new Set();
    const objectVersions = [];
    const pendingFolderKeys = new Set();
    for (const entry of selectedEntries) {
      if (entry.type === "folder") {
        const folderObjects = activeObjects.filter((item) => item.key.startsWith(entry.key));
        if (folderObjects.length === 0) pendingFolderKeys.add(entry.key);
        folderObjects.forEach((item) => {
          objectKeys.add(item.key);
          objectVersions.push({ key: item.key, versionId: isRewindMode ? item.version_id || "" : "" });
        });
      } else {
        objectKeys.add(entry.key);
        objectVersions.push({ key: entry.key, versionId: isRewindMode ? entry.version_id || "" : "" });
      }
    }

    try {
      for (const item of objectVersions) {
        await deleteObject(token, selected.name, item.key, item.versionId);
      }
      if (pendingFolderKeys.size) {
        setPendingFolders((folders) => folders.filter((key) => !pendingFolderKeys.has(key)));
      }
      setSelectedEntryKeys([]);
      if (selectedObject && objectKeys.has(selectedObject.key)) setSelectedObject(null);
      setStatus(`Deleted ${count} selected item${count === 1 ? "" : "s"}.`);
      if (objectKeys.size) await refreshObjects(selected.name);
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  async function handleDownloadSelectedEntries() {
    if (!selected || selectedEntries.length === 0) return;
    const downloadTargets = [];
    for (const entry of selectedEntries) {
      if (entry.type === "folder") {
        activeObjects
          .filter((item) => item.key.startsWith(entry.key))
          .forEach((item) =>
            downloadTargets.push({
              ...item,
              name: getObjectDisplayName(item.key, currentPrefix),
            })
          );
      } else {
        downloadTargets.push(entry);
      }
    }
    for (const item of downloadTargets) {
      await handleDownloadObject(item, isRewindMode ? item.version_id || "" : "");
    }
  }

  function toggleVersionMultiSelect() {
    setVersionMultiSelect((enabled) => {
      if (enabled) setSelectedVersionIds([]);
      return !enabled;
    });
  }

  function toggleSelectedVersion(versionId) {
    if (!versionId) return;
    setSelectedVersionIds((ids) =>
      ids.includes(versionId) ? ids.filter((id) => id !== versionId) : [...ids, versionId]
    );
  }

  async function handleDeleteSelectedVersions() {
    if (!selected || !selectedObject || selectedVersionIds.length === 0 || !canWriteKey(selectedObject.key)) return;
    const count = selectedVersionIds.length;
    if (!window.confirm(`Delete ${count} selected version${count === 1 ? "" : "s"}? This cannot be undone.`)) return;

    try {
      for (const versionId of selectedVersionIds) {
        await deleteObject(token, selected.name, selectedObject.key, versionId);
      }
      setVersionItems((items) => items.filter((item) => !selectedVersionIds.includes(item.version_id || "")));
      setSelectedVersionIds([]);
      setStatus(`Deleted ${count} selected version${count === 1 ? "" : "s"}.`);
      await refreshObjects(selected.name);
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  async function handleDeleteObject() {
    if (!selected || !selectedObject || !canWriteKey(selectedObject.key)) return;
    const objectName = selectedObject.name;
    if (!window.confirm(`Delete "${objectName}"? This cannot be undone.`)) return;
    try {
      await deleteObject(token, selected.name, selectedObject.key, isRewindMode ? selectedObject.version_id || "" : "");
      setObjects((items) => items.filter((item) => item.key !== selectedObject.key));
      if (isRewindMode) {
        setRewindObjects((items) =>
          items.filter((item) => !(item.key === selectedObject.key && item.version_id === selectedObject.version_id))
        );
      }
      setSelectedObject(null);
      setStatus(`Deleted "${objectName}".`);
    } catch (error) {
      if (error.status === 401) {
        onAuthExpired();
        return;
      }
      setStatus(error.message);
    }
  }

  return (
    <main className="browser-shell">
      <aside className="browser-sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-minio">MINIO</div>
          <div className="sidebar-title">OBJECT <span>STORE</span></div>
          <button className="collapse-button" aria-label="Collapse sidebar" title="Collapse sidebar">
            <ArrowLeft size={20} />
          </button>
        </div>

        {hasGlobalWrite ? (
          <button className="sidebar-action" title="Create a new bucket" onClick={() => setModalOpen(true)}>
            <span><Plus size={24} /></span>
            Create Bucket
          </button>
        ) : null}

        {canManageUsers ? (
          <button
            className={activeView === "admin" ? "sidebar-action active-admin" : "sidebar-action"}
            title="Manage users and visibility grants"
            onClick={() => setActiveView((value) => (value === "admin" ? "browser" : "admin"))}
          >
            <span><Users size={24} /></span>
            Admin
          </button>
        ) : null}

        <label className="bucket-filter">
          <Search size={21} aria-hidden="true" />
          <input
            placeholder="Filter Buckets"
            value={bucketFilter}
            onChange={(event) => setBucketFilter(event.target.value)}
          />
        </label>

        <div className="sidebar-section-title">Buckets</div>
        <div className="bucket-nav" aria-label="Buckets">
          {filteredBuckets.map((bucket) => (
            <button
              className={bucket.name === selectedBucket ? "bucket-nav-item active" : "bucket-nav-item"}
              key={bucket.name}
              title={`Open bucket ${bucket.name}`}
              onClick={() => {
                setActiveView("browser");
                onSelectBucket(bucket.name);
              }}
            >
              <span><ShoppingBasket size={18} fill="currentColor" /></span>
              {bucket.name}
            </button>
          ))}
        </div>

        <div className="sidebar-spacer" />

        <a className="sidebar-link" href="https://min.io/docs/minio/linux/index.html">
          <span><BookOpenText size={18} /></span>
          Documentation
        </a>
        <a className="sidebar-link" href="https://min.io/docs/minio/linux/operations/install-deploy-manage/deploy-minio-community-edition.html">
          <span><ClipboardCheck size={18} /></span>
          License
        </a>
        <button className="sidebar-link signout" title="Sign out" onClick={onSignOut}>
          <span><LogOut size={18} /></span>
          Sign Out
        </button>
      </aside>

      <section className="browser-main">
        <header className="browser-header">
          <h1>Object Browser</h1>
          {selectedBucket ? (
            <label className="object-search">
              <Search size={22} />
              <input
                placeholder="Start typing to filter objects in the bucket"
                value={objectFilter}
                onChange={(event) => setObjectFilter(event.target.value)}
              />
            </label>
          ) : null}
          <div className="header-actions">
            <div className="transfers-wrap">
              <button
                aria-label="Downloads and uploads"
                className="transfers-button"
                title="Downloads and uploads"
                onClick={() => setTransfersOpen((value) => !value)}
              >
                <Download size={22} />
                <Upload size={22} />
                {activeTransferCount ? <span /> : null}
              </button>
              {isTransfersOpen ? (
                <section className="transfers-panel" aria-label="Downloads and uploads">
                  <header>
                    <h2>Downloads / Uploads</h2>
                    <button
                      type="button"
                      aria-label="Close transfers"
                      title="Close transfers"
                      onClick={() => setTransfersOpen(false)}
                    >
                      <X size={16} />
                    </button>
                  </header>
                  <div className="transfers-list">
                    {transfers.length ? (
                      transfers.map((item) => (
                        <article className="transfer-item" key={item.id}>
                          <div className="transfer-title-row">
                            {item.status === "done" ? (
                              <CheckCircle size={24} />
                            ) : (
                              <Upload size={24} />
                            )}
                            <div>
                              <strong>{item.name}</strong>
                              <p><b>Bucket:</b> {item.bucket}</p>
                            </div>
                            <button
                              type="button"
                              aria-label={`Remove ${item.name} from transfers`}
                              title="Remove transfer"
                              onClick={() => removeTransfer(item.id)}
                            >
                              <X size={20} />
                            </button>
                          </div>
                          <div className="transfer-progress-row">
                            <div>
                              <span style={{ width: `${item.progress}%` }} />
                            </div>
                            <strong>{item.progress}%</strong>
                          </div>
                        </article>
                      ))
                    ) : (
                      <p className="empty-transfers">No downloads or uploads yet.</p>
                    )}
                  </div>
                </section>
              ) : null}
            </div>
          </div>
        </header>

        <div className="browser-content">
          {activeView === "admin" && canManageUsers ? (
            <AdminPanel
              currentUser={currentUser}
              users={adminUsers}
              groups={accessGroups}
              grants={visibilityGrants}
              assignableUsers={adminAssignableUsers}
              grantGroups={grantGroups}
              meta={adminMeta}
              filters={adminFilters}
              setFilters={setAdminFilters}
              buckets={buckets}
              newUser={newUser}
              setNewUser={setNewUser}
              newGrant={newGrant}
              setNewGrant={setNewGrant}
              isLoading={isAdminLoading}
              onCreateUser={handleCreateUser}
              onUpdateUser={handleUpdateUser}
              onDeactivateUser={handleDeactivateUser}
              onCreateGroup={handleCreateGroup}
              onUpdateGroup={handleUpdateGroup}
              onEditGroup={handleEditGroup}
              onCancelEditGroup={() => setEditingGroup(null)}
              onDeleteGroup={handleDeleteGroup}
              onCreateGrant={handleCreateGrant}
              onDeleteGrant={handleDeleteGrant}
              onRefresh={refreshAdminData}
              editingGroup={editingGroup}
            />
          ) : selected ? (
            <section className="bucket-browser">
              <header className="bucket-browser-header">
                <div className="bucket-title-row">
                  <ShoppingBasket size={45} fill="currentColor" />
                  <div>
                    <h2>{selected.name}</h2>
                    <p>
                      Created on: <strong>{formatCreatedAt(selected.createdAt)}</strong>
                      <span>Access: <strong>PRIVATE</strong></span>
                      <span>{formatBytes(totalSize)} - {objectCount} Object{objectCount === 1 ? "" : "s"}</span>
                    </p>
                  </div>
                </div>
                <div className="bucket-toolbar">
                  <button
                    type="button"
                    className={isRewindMode ? "active-rewind-button" : ""}
                    title={isRewindMode ? "Viewing rewind data" : "Show bucket data from an earlier time"}
                    onClick={handleOpenRewind}
                  >
                    Rewind <RefreshCw size={18} />
                  </button>
                  <button
                    onClick={() => {
                      clearRewindData();
                      refreshObjects(selected.name);
                    }}
                    title="Reload objects in this bucket"
                  >
                    Refresh <RefreshCw size={18} />
                  </button>
                  {canWriteCurrentPrefix ? (
                  <div className="upload-menu-wrap">
                    <button
                      className="upload-button"
                      disabled={isUploading}
                      title="Upload files or folders"
                      onClick={() => setUploadMenuOpen((value) => !value)}
                    >
                      {isUploading ? "Uploading..." : "Upload"} <Upload size={20} />
                    </button>
                    {isUploadMenuOpen ? (
                      <div className="upload-menu">
                        <button
                          title="Choose files to upload"
                          onClick={() => {
                            setUploadMenuOpen(false);
                            fileInputRef.current?.click();
                          }}
                        >
                          <Upload size={28} /> Upload File
                        </button>
                        <button
                          title="Choose a folder to upload"
                          onClick={() => {
                            setUploadMenuOpen(false);
                            folderInputRef.current?.click();
                          }}
                        >
                          <Upload size={28} /> Upload Folder
                        </button>
                      </div>
                    ) : null}
                  </div>
                  ) : null}
                </div>
              </header>

              <div className={hasObjectSidePanel ? "path-row path-row-with-panel" : "path-row"}>
                <button
                  aria-label="Back"
                  title={isVersionsMode ? "Back to object list" : selectedObject ? "Back to object list" : "Go to parent path"}
                  disabled={!isVersionsMode && !selectedObject && !currentPrefix}
                  onClick={handlePathBack}
                >
                  ‹
                </button>
                <div>{displayedPathLabel}</div>
                <button
                  aria-label={isPathCopied ? "Path copied" : "Copy path"}
                  title={isPathCopied ? "Path copied" : "Copy path"}
                  onClick={handleCopyPath}
                >
                  {isPathCopied ? <ClipboardCheck size={18} /> : <Copy size={18} />}
                </button>
                <button
                  aria-label="Create new path"
                  className="path-create-button"
                  title="Create a folder-like path in this bucket"
                  disabled={selectedEntryCount > 0 || !canWriteCurrentPrefix}
                  onClick={() => setPathModalOpen(true)}
                >
                  Create new path <FolderPlus size={18} />
                </button>
              </div>

              <div className={hasObjectSidePanel ? "object-workspace has-object-panel" : "object-workspace"}>
                {isVersionsMode && selectedObject ? (
                  <section className="versions-view" aria-label={`${selectedObject.name} versions`}>
                    <header className="versions-heading">
                      <div className="versions-title">
                        <History size={30} fill="currentColor" aria-hidden="true" />
                        <div>
                          <h3>{selectedObject.name} Versions</h3>
                          <p>
                            {versionItems.length} Version{versionItems.length === 1 ? "" : "s"}
                            <span>{formatBytes(versionTotalSize)}</span>
                          </p>
                        </div>
                      </div>
                      <div className="versions-toolbar">
                        <button
                          type="button"
                          className={isVersionMultiSelect ? "active" : ""}
                          title={isVersionMultiSelect ? "Exit multiple select" : "Select multiple versions"}
                          onClick={toggleVersionMultiSelect}
                        >
                          <span aria-hidden="true">▦</span>
                        </button>
                        <button
                          type="button"
                          title={selectedVersionCount ? `Delete ${selectedVersionCount} selected version${selectedVersionCount === 1 ? "" : "s"}` : "Select versions to delete"}
                          disabled={!selectedVersionCount || !canWriteKey(selectedObject.key)}
                          onClick={handleDeleteSelectedVersions}
                        >
                          <Trash2 size={22} />
                        </button>
                        <button type="button" title="Timeline version layout">
                          <History size={22} />
                        </button>
                        <label>
                          Sort by
                          <select value={versionSort} onChange={(event) => setVersionSort(event.target.value)}>
                            <option value="date">Date</option>
                            <option value="size">Size</option>
                          </select>
                        </label>
                      </div>
                    </header>

                    {isLoadingVersions ? (
                      <p className="empty-location">Loading versions...</p>
                    ) : sortedVersionItems.length ? (
                      <div className="versions-timeline">
                        {sortedVersionItems.map((version, index) => {
                          const versionNumber = sortedVersionItems.length - index;
                          const versionId = version.version_id || "";
                          const isNullVersion = versionId === "null" || !versionId;
                          const canOpenVersion = !version.is_delete_marker;
                          const isChecked = selectedVersionIds.includes(versionId);
                          return (
                            <article
                              className={[
                                "version-row",
                                isVersionMultiSelect ? "with-select" : "",
                                isChecked ? "selected" : "",
                              ].filter(Boolean).join(" ")}
                              key={`${versionId}-${index}`}
                            >
                              {isVersionMultiSelect ? (
                                <label className="version-select">
                                  <input
                                    type="checkbox"
                                    checked={isChecked}
                                    disabled={!versionId}
                                    aria-label={`Select version ${versionNumber}`}
                                    onChange={() => toggleSelectedVersion(versionId)}
                                  />
                                </label>
                              ) : null}
                              <div className="version-main">
                                <FileTypeIcon name={selectedObject.name} />
                                <div>
                                  <h4>
                                    v{versionNumber}
                                    {version.is_latest ? <span className="current-version-badge">CURRENT VERSION</span> : null}
                                    {isNullVersion ? <span className="null-version-badge">NULL VERSION</span> : null}
                                    {version.is_delete_marker ? <span className="null-version-badge">DELETE MARKER</span> : null}
                                  </h4>
                                  <p className="version-id">{versionId || "-"}</p>
                                  <p className="version-meta">
                                    <strong>Last modified:</strong> {version.last_modified ? formatCreatedAt(version.last_modified) : "Unknown"}
                                    <strong>Size:</strong> {formatBytes(version.size)}
                                  </p>
                                </div>
                              </div>
                              <div className="version-actions">
                                <button
                                  type="button"
                                  aria-label={`Preview version ${versionNumber}`}
                                  title="Preview this version"
                                  disabled={!canOpenVersion}
                                  onClick={() => handleOpenPreview(selectedObject, versionId)}
                                >
                                  <Eye size={18} />
                                </button>
                                <button
                                  type="button"
                                  aria-label={`Download version ${versionNumber}`}
                                  title="Download this version"
                                  disabled={!canOpenVersion}
                                  onClick={() => handleDownloadObject(selectedObject, versionId)}
                                >
                                  <Download size={18} />
                                </button>
                                <button
                                  type="button"
                                  aria-label={`Share version ${versionNumber}`}
                                  title="Share this version"
                                  disabled={!canOpenVersion}
                                  onClick={() => handleOpenShare(selectedObject, versionId)}
                                >
                                  <Share2 size={18} />
                                </button>
                                <button
                                  type="button"
                                  aria-label={`Restore version ${versionNumber}`}
                                  title="Restore version is not available yet"
                                  disabled
                                >
                                  <RefreshCw size={18} />
                                </button>
                              </div>
                            </article>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="empty-location">No versions found for this object.</p>
                    )}
                  </section>
                ) : objectEntries.length === 0 ? (
                  <p className="empty-location">
                    {isLoading ? "Loading..." : "This location is empty, please try uploading a new file"}
                  </p>
                ) : (
                  <div className="object-table">
                    <div className="object-row object-row-header">
                      <label className="object-select-cell">
                        <input
                          type="checkbox"
                          checked={areAllVisibleEntriesSelected}
                          aria-label="Select all visible files and folders"
                          onChange={toggleAllVisibleEntries}
                        />
                      </label>
                      <span>Name</span>
                      <span>{selectedEntryCount || isRewindMode ? "Object Date" : "Last Modified"}</span>
                      <span>Size</span>
                      <span>Deleted</span>
                    </div>
                    {isRewindMode ? (
                      <div className="rewind-table-banner">
                        <span>Rewind: {formatCreatedAt(rewindAppliedAt)}</span>
                        <button type="button" onClick={clearRewindData}>Show current data</button>
                      </div>
                    ) : null}
                    {objectEntries.map((item) => (
                      <div
                        className={[
                          "object-row",
                          item.type === "folder" ? "folder-row" : "file-row",
                          selectedObject?.key === item.key ? "selected" : "",
                          selectedEntryKeys.includes(item.key) ? "checked" : "",
                        ].filter(Boolean).join(" ")}
                        key={item.key}
                      >
                        <label className="object-select-cell">
                          <input
                            type="checkbox"
                            checked={selectedEntryKeys.includes(item.key)}
                            aria-label={`Select ${item.name}`}
                            onChange={() => toggleEntrySelection(item.key)}
                          />
                        </label>
                        <button
                          className="object-open-button object-name"
                          type="button"
                          title={item.type === "folder" ? `Open folder ${item.name}` : `View details for ${item.name}`}
                          onClick={() => openObjectEntry(item)}
                        >
                          {item.type === "folder" ? (
                            <Folder className="folder-icon" size={22} fill="currentColor" />
                          ) : (
                            <FileTypeIcon name={item.name} />
                          )}
                          {item.name}
                        </button>
                        <button
                          className="object-open-button"
                          type="button"
                          tabIndex={-1}
                          onClick={() => openObjectEntry(item)}
                        >
                          {item.last_modified ? formatCreatedAt(item.last_modified) : ""}
                        </button>
                        <button
                          className="object-open-button"
                          type="button"
                          tabIndex={-1}
                          onClick={() => openObjectEntry(item)}
                        >
                          {item.type === "folder" ? "-" : formatBytes(item.size)}
                        </button>
                        <button
                          className="object-open-button"
                          type="button"
                          tabIndex={-1}
                          onClick={() => openObjectEntry(item)}
                        >
                          No
                        </button>
                      </div>
                    ))}
                    {!isRewindMode && isObjectListTruncated ? (
                      <div className="object-list-footer">
                        <button
                          type="button"
                          disabled={isLoading}
                          title="Load next page of objects"
                          onClick={loadMoreObjects}
                        >
                          {isLoading ? "Loading..." : "Load more"}
                        </button>
                      </div>
                    ) : null}
                  </div>
                )}

                {selectedEntryCount ? (
                  <aside className="object-details-panel selected-objects-panel" aria-label="Selected objects">
                    <header className="selected-objects-header">
                      <h3>Selected Objects:</h3>
                      <button
                        type="button"
                        aria-label="Clear selected objects"
                        title="Clear selected objects"
                        onClick={() => setSelectedEntryKeys([])}
                      >
                        <X size={20} />
                      </button>
                    </header>

                    <section className="object-actions selected-actions" aria-label="Selected object actions">
                      <h3>Actions:</h3>
                      <button
                        type="button"
                        title="Download selected objects"
                        onClick={handleDownloadSelectedEntries}
                      >
                        <Download size={18} /> Download
                      </button>
                      <button
                        type="button"
                        title={selectedSingleFile ? "Share selected object" : "Select one file to share"}
                        disabled={!selectedSingleFile}
                        onClick={() => handleOpenShare(selectedSingleFile)}
                      >
                        <Share2 size={18} /> Share
                      </button>
                      <button
                        type="button"
                        title={selectedSingleFile ? "Preview selected object" : "Select one file to preview"}
                        disabled={!selectedSingleFile}
                        onClick={() => handleOpenPreview(selectedSingleFile)}
                      >
                        <Eye size={18} /> Preview
                      </button>
                      <button type="button" disabled title="Anonymous access is not available">
                        <LockKeyhole size={18} /> Anonymous Access
                      </button>
                      <button
                        type="button"
                        title={`Delete ${selectedEntryCount} selected object${selectedEntryCount === 1 ? "" : "s"}`}
                        disabled={!canDeleteSelectedEntries}
                        onClick={handleDeleteSelectedEntries}
                      >
                        <Trash2 size={18} /> Delete
                      </button>
                    </section>
                  </aside>
                ) : selectedObject ? (
                  <aside className="object-details-panel" aria-label="Object details">
                    <header className="object-details-header">
                      <FileTypeIcon name={selectedObject.name} />
                      <strong title={selectedObject.name}>{selectedObject.name}</strong>
                      <button
                        type="button"
                        aria-label="Close object details"
                        title="Close object details"
                        onClick={() => setSelectedObject(null)}
                      >
                        <X size={20} />
                      </button>
                    </header>

                    <section className="object-actions" aria-label="Object actions">
                      <h3>Actions:</h3>
                      <button
                        type="button"
                        title="Download selected object"
                        onClick={() => handleDownloadObject()}
                      >
                        <Download size={18} /> Download
                      </button>
                      <button
                        type="button"
                        title="Share selected object"
                        onClick={() => handleOpenShare()}
                      >
                        <Share2 size={18} /> Share
                      </button>
                      <button
                        type="button"
                        title="Preview selected object"
                        onClick={() => handleOpenPreview()}
                      >
                        <Eye size={18} /> Preview
                      </button>
                      {canWriteKey(selectedObject.key) ? (
                        <button
                          type="button"
                          title="Edit object tags"
                          onClick={handleOpenTags}
                        >
                          <Tag size={18} /> Tags
                        </button>
                      ) : null}
                      <button
                        type="button"
                        title={isVersionsMode ? "Hide object versions" : "Display object versions"}
                        onClick={isVersionsMode ? handleHideVersions : handleDisplayVersions}
                      >
                        <History size={18} /> {isVersionsMode ? "Hide Object Versions" : "Display Object Versions"}
                      </button>
                    </section>

                    {canWriteKey(selectedObject.key) ? (
                      <button
                        className="delete-object-button"
                        type="button"
                        title="Delete selected object"
                        onClick={handleDeleteObject}
                      >
                        <Trash2 size={20} /> Delete
                      </button>
                    ) : null}

                    <section className="object-info">
                      <div className="details-section-heading">
                        <h3>Object Info</h3>
                        <ShoppingBasket size={32} fill="currentColor" aria-hidden="true" />
                      </div>
                      <dl>
                        <div>
                          <dt>Name:</dt>
                          <dd>{selectedObject.name}</dd>
                        </div>
                        <div>
                          <dt>Path:</dt>
                          <dd>{`${selected.name}/${selectedObject.key}`}</dd>
                        </div>
                        <div>
                          <dt>Size:</dt>
                          <dd>{formatBytes(selectedObject.size)}</dd>
                        </div>
                        {isVersionsMode ? (
                          <div>
                            <dt>Versions:</dt>
                            <dd>{versionItems.length} versions, {formatBytes(versionTotalSize)}</dd>
                          </div>
                        ) : null}
                        <div>
                          <dt>Last Modified:</dt>
                          <dd>{selectedObject.last_modified ? formatCreatedAt(selectedObject.last_modified) : "Unknown"}</dd>
                        </div>
                        <div>
                          <dt>ETAG:</dt>
                          <dd>{selectedObject.etag || "N/A"}</dd>
                        </div>
                        <div>
                          <dt>Tags:</dt>
                          <dd>
                            {selectedTagEntries.length
                              ? selectedTagEntries.map(([name, value]) => `${name}=${value}`).join(", ")
                              : "N/A"}
                          </dd>
                        </div>
                        <div>
                          <dt>Legal Hold:</dt>
                          <dd>Off</dd>
                        </div>
                        <div>
                          <dt>Retention Policy:</dt>
                          <dd>None</dd>
                        </div>
                      </dl>
                    </section>

                    <section className="object-metadata">
                      <div className="details-section-heading">
                        <h3>Metadata</h3>
                        <FileText size={32} aria-hidden="true" />
                      </div>
                      <dl>
                        <div>
                          <dt>Content-Type</dt>
                          <dd>{getContentType(selectedObject)}</dd>
                        </div>
                        {selectedMetadataEntries.map(([name, value]) => (
                          <div key={name}>
                            <dt>{name}</dt>
                            <dd>{value}</dd>
                          </div>
                        ))}
                      </dl>
                    </section>
                  </aside>
                ) : null}
              </div>
            </section>
          ) : (
            <section className="bucket-card">
              <div className="bucket-heading">
                <ShoppingBasket size={42} fill="currentColor" />
                <h2>Buckets</h2>
              </div>
              <p>
                MinIO uses buckets to organize objects. A bucket is similar to a folder or
                directory in a filesystem, where each bucket can hold an arbitrary number of objects.
              </p>
              {hasGlobalWrite ? (
                <p>
                  To get started,{" "}
                  <button
                    className="inline-link"
                    title="Create a new bucket"
                    onClick={() => setModalOpen(true)}
                  >
                    Create a Bucket.
                  </button>
                </p>
              ) : (
                <p>No buckets are available for your account yet.</p>
              )}
            </section>
          )}

          {status ? <p className="browser-status">{status}</p> : null}
        </div>
      </section>

      {isModalOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={closeModals}>
          <form className="bucket-modal" onSubmit={handleCreateBucket} onClick={(event) => event.stopPropagation()}>
            <button
              className="modal-close"
              type="button"
              aria-label="Close"
              title="Close dialog"
              onClick={() => setModalOpen(false)}
            >
              <X size={42} />
            </button>
            <h2>Create Bucket</h2>
            <label>
              <span>Bucket Name*</span>
              <input
                autoFocus
                value={bucketName}
                onChange={(event) => setBucketName(event.target.value)}
                placeholder="my-bucket"
              />
            </label>
            <label>
              <span>Access Group</span>
              <select
                value={bucketGroupId}
                onChange={(event) => setBucketGroupId(event.target.value)}
              >
                <option value="">Open to everyone</option>
                {accessGroups.map((group) => (
                  <option key={group.id} value={group.id}>{group.name}</option>
                ))}
              </select>
            </label>
            <p className="modal-help">
              Default opens bucket to all viewers/editors. Pick a group to restrict access to that group.
            </p>
            {bucketName && !isValidBucketName ? <p className="modal-help invalid">Invalid bucket name</p> : null}
            {status ? <p className="modal-status">{status}</p> : null}
            <div className="modal-actions">
              <button type="button" title="Clear bucket name" onClick={() => {
                setBucketName("");
                setBucketGroupId("");
                setStatus("");
              }}>Clear</button>
              <button className="primary" disabled={!canCreate} title="Create bucket">
                {isCreating ? "Creating..." : "Create Bucket"}
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {isPathModalOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={closeModals}>
          <form className="bucket-modal path-modal" onSubmit={handleCreatePath} onClick={(event) => event.stopPropagation()}>
            <button
              className="modal-close"
              type="button"
              aria-label="Close"
              title="Close dialog"
              onClick={() => setPathModalOpen(false)}
            >
              <X size={42} />
            </button>
            <h2>
              <FolderPlus className="path-mark" size={32} aria-hidden="true" />
              Choose or create a new path
            </h2>
            <p className="path-current">
              <strong>Current Path:</strong>
              <span>{currentPath}</span>
            </p>
            <label>
              <span>New Folder Path*</span>
              <input
                autoFocus
                value={newFolderPath}
                onChange={(event) => setNewFolderPath(event.target.value)}
                placeholder="Enter the new Folder Path"
              />
            </label>
            <div className="modal-actions">
              <button type="button" title="Clear folder path" onClick={() => setNewFolderPath("")}>Clear</button>
              <button className="primary" disabled={!canCreatePath} title="Create path">Create</button>
            </div>
          </form>
        </div>
      ) : null}

      {isRewindModalOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={closeModals}>
          <section className="rewind-modal" role="dialog" aria-modal="true" aria-labelledby="rewind-title" onClick={(event) => event.stopPropagation()}>
            <button
              className="modal-close"
              type="button"
              aria-label="Close"
              title="Close dialog"
              onClick={() => setRewindModalOpen(false)}
            >
              <X size={42} />
            </button>
            <h2 id="rewind-title">Rewind - {selected?.name}</h2>

            <label className="rewind-field">
              <span>Rewind to</span>
              <input
                type="datetime-local"
                value={rewindDate}
                onChange={(event) => setRewindDate(event.target.value)}
              />
            </label>

            <div className="rewind-status-row">
              <strong>Current Status</strong>
              <label className="rewind-toggle">
                <span>Disabled</span>
                <input
                  type="checkbox"
                  checked={isRewindEnabled}
                  onChange={(event) => setRewindEnabled(event.target.checked)}
                />
                <i aria-hidden="true" />
                <span>Enabled</span>
              </label>
            </div>

            <div className="rewind-actions">
              <button
                type="button"
                disabled={!isRewindEnabled || !rewindDate || isLoadingRewind}
                title="Show rewind data"
                onClick={handleShowRewindData}
              >
                {isLoadingRewind ? "Loading..." : "Show Rewind Data"}
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {isPreviewModalOpen ? (
        <div className="modal-backdrop preview-backdrop" role="presentation" onClick={closeModals}>
          <section className="preview-modal" role="dialog" aria-modal="true" aria-labelledby="preview-title" onClick={(event) => event.stopPropagation()}>
            <div className="preview-header">
              <h2 id="preview-title">
                <Eye className="preview-title-icon" size={34} aria-hidden="true" />
                Preview - {(previewTarget || selectedObject)?.key}
              </h2>
              <button
                className="preview-close"
                type="button"
                aria-label="Close preview"
                title="Close preview"
                onClick={() => setPreviewModalOpen(false)}
              >
                <X size={36} />
              </button>
            </div>
            <div className="preview-notice">
              <strong>File Preview</strong>
              <p>
                This is a file preview. If you need to work with the full document,
                download the file instead.
              </p>
              <button type="button" title="Download file" onClick={() => handleDownloadObject(previewTarget || selectedObject, previewVersionId)}>
                Download File
              </button>
            </div>
            <div className="preview-frame-wrap">
              {isLoadingPreview ? (
                <div className="preview-loading">Loading preview...</div>
              ) : (
                <iframe
                  src={previewUrl}
                  title={`Preview ${(previewTarget || selectedObject)?.name || "object"}`}
                />
              )}
            </div>
          </section>
        </div>
      ) : null}

      {isShareModalOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={closeModals}>
          <section className="share-modal" role="dialog" aria-modal="true" aria-labelledby="share-title" onClick={(event) => event.stopPropagation()}>
            <button
              className="modal-close"
              type="button"
              aria-label="Close"
              title="Close dialog"
              onClick={() => setShareModalOpen(false)}
            >
              <X size={42} />
            </button>
            <h2 id="share-title">
              <Share2 className="share-title-icon" size={34} aria-hidden="true" />
              Share File
            </h2>
            <p>
              The following URL lets you share this object without requiring a login.
              The URL expires automatically at the earlier of your configured time or the expiration
              of your current web session.
            </p>

            <div className="share-duration">
              <strong>Active for</strong>
              <label>
                <input
                  min="0"
                  max="7"
                  type="number"
                  value={shareDays}
                  onChange={(event) => setShareDays(event.target.value)}
                />
                Days
              </label>
              <label>
                <input
                  min="0"
                  max="168"
                  type="number"
                  value={shareHours}
                  onChange={(event) => setShareHours(event.target.value)}
                />
                Hours
              </label>
              <label>
                <input
                  min="0"
                  max="59"
                  type="number"
                  value={shareMinutes}
                  onChange={(event) => setShareMinutes(event.target.value)}
                />
                Minutes
              </label>
              <button
                className="share-generate-button"
                type="button"
                disabled={isCreatingShare}
                title="Create share link"
                onClick={() => createShareLink()}
              >
                {isCreatingShare ? "Creating..." : shareUrl ? "Refresh Link" : "Create Link"}
              </button>
            </div>

            <div className="share-expiry">
              <Link size={20} aria-hidden="true" />
              <span>Link will be available until:</span>
              <strong>{shareExpiresAt ? formatShareExpiryTime(shareExpiresAt) : "-"}</strong>
            </div>

            <div className="share-url-row">
              <input readOnly value={shareUrl} placeholder="Create a link to share this object" />
              <button
                type="button"
                aria-label="Copy share link"
                title="Copy share link"
                disabled={!shareUrl}
                onClick={handleCopyShareUrl}
              >
                <Copy size={24} />
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {isTagsModalOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={closeModals}>
          <form className="tags-edit-modal" onSubmit={handleSaveTags} onClick={(event) => event.stopPropagation()}>
            <button
              className="modal-close tags-close"
              type="button"
              aria-label="Close"
              title="Close dialog"
              onClick={() => setTagsModalOpen(false)}
            >
              <X size={42} />
            </button>
            <h2 id="tags-title">
              <Tag className="tags-title-icon" size={34} aria-hidden="true" />
              Edit Tags
            </h2>
            <p className="tags-object-name">
              Tags for: <strong>{selectedObject?.name}</strong>
            </p>

            <section className="current-tags">
              <h3>Current Tags:</h3>
              {Object.keys(currentTags).length ? (
                <div className="current-tags-list">
                  {Object.entries(currentTags).map(([key, value]) => (
                    <span className="tag-pill" key={key}>
                      {key} : {value}
                      <button
                        type="button"
                        aria-label={`Remove tag ${key}`}
                        title={`Remove tag ${key}`}
                        disabled={isSavingTags}
                        onClick={() => handleRemoveTag(key)}
                      >
                        <X size={20} />
                      </button>
                    </span>
                  ))}
                </div>
              ) : (
                <p>There are no tags for this object</p>
              )}
            </section>

            <section className="add-tag-section">
              <h3>
                <Tag className="tags-title-icon" size={28} aria-hidden="true" />
                Add New Tag
              </h3>
              <label>
                <span>Tag Key</span>
                <input
                  autoFocus
                  value={tagKey}
                  onChange={(event) => setTagKey(event.target.value)}
                  placeholder="Enter Tag Key"
                />
              </label>
              <label>
                <span>Tag Label</span>
                <input
                  value={tagLabel}
                  onChange={(event) => setTagLabel(event.target.value)}
                  placeholder="Enter Tag Label"
                />
              </label>
            </section>

            <div className="tags-actions">
              <button type="button" title="Clear tag form" onClick={handleClearTagForm}>Clear</button>
              <button className="primary" disabled={isSavingTags || !tagKey.trim() || !tagLabel.trim()} title="Save object tag">
                {isSavingTags ? "Saving..." : "Save"}
              </button>
            </div>
          </form>
        </div>
      ) : null}

      <input
        ref={fileInputRef}
        className="hidden-file-input"
        type="file"
        multiple
        onChange={handleUploadFileChange}
      />
      <input
        ref={folderInputRef}
        className="hidden-file-input"
        type="file"
        multiple
        webkitdirectory=""
        directory=""
        onChange={handleUploadFolderChange}
      />
    </main>
  );
}

function formatCreatedAt(value) {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZoneName: "short",
  }).format(new Date(value));
}

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

createRoot(document.getElementById("root")).render(<App />);

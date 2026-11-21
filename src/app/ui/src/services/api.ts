/**
 * API client for the tapedeck FastAPI backend.
 * All functions return parsed JSON or throw on non-ok responses.
 */

const API_BASE = ''

async function request(
  path: string,
  init?: RequestInit,
): Promise<unknown> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    let detail: string | undefined
    try {
      const body = await res.json()
      detail = typeof body === 'object' && body !== null && 'error' in body
        ? String(body.error)
        : undefined
    } catch { /* ignore parse errors */ }
    throw new Error(detail || `API error ${res.status} for ${path}`)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  // ------------------------------------------------- playlists

  listPlaylists: () => request('/api/playlists') as Promise<{
    playlists: Playlist[]
  }>,

  getPlaylist: (name: string, etag?: string) =>
    request(`/api/playlists/${encodeURIComponent(name)}`, {
      headers: etag ? { 'If-Match': etag } : {},
    }) as Promise<PlaylistDetail>,

  createPlaylist: (name: string, entries: PlaylistEntry[] = []) =>
    request('/api/playlists', {
      method: 'POST',
      body: JSON.stringify({ path: name, entries }),
    }) as Promise<{ ok: true }>,

  renamePlaylist: (name: string, newName: string) =>
    request(`/api/playlists/${encodeURIComponent(name)}`, {
      method: 'PATCH',
      body: JSON.stringify({ new_name: newName }),
    }) as Promise<{ ok: true; name: string }>,

  deletePlaylist: (name: string) =>
    request(`/api/playlists/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }) as Promise<{ ok: true; history: string }>,

  undoPlaylist: (name: string) =>
    request(`/api/playlists/${encodeURIComponent(name)}/undo`, {
      method: 'POST',
    }) as Promise<{ ok: true; name: string }>,

  applyOps: (
    name: string,
    ops: Op[],
    etag?: string,
  ) =>
    request(`/api/playlists/${encodeURIComponent(name)}/ops`, {
      method: 'POST',
      body: JSON.stringify({ etag, ops }),
    }) as Promise<{ etag: string; ops: OpResult[] }>,

  relinkPlaylist: (name: string) =>
    request(`/api/playlists/${encodeURIComponent(name)}/relink`, {
      method: 'POST',
    }) as Promise<{ relocated: any[]; ambiguous: any[]; missing: any[] }>,

  detachPlaylist: (name: string) =>
    request(`/api/playlists/${encodeURIComponent(name)}/detach`, {
      method: 'POST',
    }) as Promise<{ ok: true; kind: string; source_id: string }>,

  reattachPlaylist: (name: string, mode: 'merge' | 'replace') =>
    request(`/api/playlists/${encodeURIComponent(name)}/reattach`, {
      method: 'POST',
      body: JSON.stringify({ mode }),
    }) as Promise<{
      ok: true; kind: string; source_id: string; mode: string;
      new_on_spotify: number; local_kept: number; removed_locally: number;
    }>,

  refreshPlaylist: (name: string) =>
    request(`/api/playlists/${encodeURIComponent(name)}/refresh`, {
      method: 'POST',
    }) as Promise<{ ok: true; kind: string; source_id: string; result: any }>,

  rebuildPlaylist: (name: string) =>
    request(`/api/playlists/${encodeURIComponent(name)}/rebuild`, {
      method: 'POST',
    }) as Promise<{ ok: true; kind: string; source_id: string; result: any }>,

  // ------------------------------------------------- sync

  syncPreview: () => request('/api/sync/preview') as Promise<{
    playlists: SyncPreview[]
  }>,

  syncPlaylists: () =>
    request('/api/playlists/sync', { method: 'POST' }) as Promise<{ id: string }>,

  // ------------------------------------------------- jobs

  listJobs: () => request('/api/jobs') as Promise<{ jobs: Job[] }>,

  getJob: (jobId: string) =>
    request(`/api/jobs/${encodeURIComponent(jobId)}`) as Promise<Job>,

  deleteJob: (jobId: string) =>
    request(`/api/jobs/${encodeURIComponent(jobId)}`, {
      method: 'DELETE',
    }) as Promise<{ ok: true }>,

  createJob: (
    jobType: string,
    target: string,
    organize?: string,
  ) => {
    const qs = new URLSearchParams()
    qs.set('job_type', jobType)
    qs.set('target', target)
    if (organize) qs.set('organize', organize)
    return request(`/api/jobs?${qs}`, {
      method: 'POST',
    }) as Promise<{ id: string }>
  },

  // ------------------------------------------------- links

  addLink: (url: string, path: string, artist?: string, title?: string) =>
    request('/api/links', {
      method: 'POST',
      body: JSON.stringify({ url, path, artist: artist || '', title: title || '' }),
    }) as Promise<{ ok: true; path: string }>,

  // ------------------------------------------------- library

  getLibrary: (params?: LibraryParams) => {
    const qs = new URLSearchParams()
    if (params?.q) qs.set('q', params.q)
    if (params?.artist) qs.set('artist', params.artist)
    if (params?.album) qs.set('album', params.album)
    if (params?.playlist) qs.set('playlist', params.playlist)
    if (params?.minPlaylists !== undefined) qs.set('min_playlists', String(params.minPlaylists))
    if (params?.sort) qs.set('sort', params.sort)
    if (params?.dir) qs.set('dir', params.dir)
    if (params?.offset !== undefined) qs.set('offset', String(params.offset))
    if (params?.limit !== undefined) qs.set('limit', String(params.limit))
    return request(`/api/library?${qs}`) as Promise<LibraryResult>
  },

  libraryStatus: () => request('/api/library/status') as Promise<LibraryStatus>,

  rescanLibrary: () => request('/api/library/rescan', { method: 'POST' }) as Promise<{ scanning: boolean }>,

  // ------------------------------------------------- tracks / membership

  trackPlaylists: (path: string) =>
    request(`/api/tracks/${encodeURIComponent(path)}/playlists`) as Promise<{ playlists: string[] }>,

  tracksPlaylists: (paths: string[]) =>
    request('/api/tracks/playlists', {
      method: 'POST',
      body: JSON.stringify({ paths }),
    }) as Promise<{ playlists: Record<string, string[]> }>,

  // ------------------------------------------------- config / health

  config: () => request('/api/config') as Promise<{ title: string }>,

  health: () => request('/api/health') as Promise<{
    ok: boolean; crate: string; playlists: string | null; problems: string[];
  }>,

  // ------------------------------------------------- files

  getFile: (path: string, range?: string) =>
    fetch(`${API_BASE}/files/${encodeURIComponent(path)}`, {
      headers: range ? { Range: range } : {},
    }),

  uploadCover: (name: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request(`/api/playlists/${encodeURIComponent(name)}/cover`, {
      method: 'POST',
      body: form,
    }) as Promise<{ ok: true; cover: string }>
  },
}

// ------------------------------------------------- types

export interface Playlist {
  name: string
  path: string
  kind: 'local' | 'synced' | 'detached'
  source_id: string | null
  cover: string | null
  count: number
  duration: number
  edited: boolean
  last_synced: number
}

export interface PlaylistEntry {
  id: number
  track_id: string
  artist: string
  title: string
  album: string
  length: number
  path: string | null
  rel: string
  exists: boolean
  local: boolean
  extinf: string | null
  track?: number
  disc?: number
  year?: number
}

export interface PlaylistDetail {
  name: string
  kind: 'local' | 'synced' | 'detached'
  source_id: string | null
  cover: string | null
  etag: string
  edited: boolean
  entries: PlaylistEntry[]
  ghosts: PlaylistEntry[]
  duration: number
}

export interface Op {
  op: 'add' | 'remove' | 'move'
  paths?: string[]
  ids?: number[]
  at?: number
  to?: number
}

export interface OpResult {
  op: string
  added?: number
  removed?: number
  moved?: number
  at?: number
  to?: number
  ids?: number[]
  error?: string
}

export interface SyncPreview {
  name: string
  source_id: string
  edited: boolean
  drops: number
  adds: number
  drop_details: Array<{ rel: string; artist: string; title: string }>
  add_details: Array<{ rel: string; artist: string; title: string }>
}

export interface Job {
  id: string
  type: string
  state: 'queued' | 'running' | 'ok' | 'error'
  log: string[]
  progress: { current: number; total: number; pct: number }
  result: unknown
  error: string | null
  meta: { target: string; organize: string }
  created_at: number
  updated_at: number
}

export interface LibraryParams {
  q?: string
  artist?: string
  album?: string
  playlist?: string
  minPlaylists?: number
  sort?: 'artist' | 'album' | 'title' | 'path'
  dir?: 'asc' | 'desc'
  offset?: number
  limit?: number
}

export interface LibraryRow {
  path: string
  artist: string
  albumartist: string
  album: string
  title: string
  track: number
  disc: number
  year: number
  length: number
  url: string
  playlists?: string[]
}

export interface LibraryResult {
  total: number
  rows: LibraryRow[]
  archive_path: string
  scanning: boolean
  error?: string
}

export interface LibraryStatus {
  state: string
  scanned: number
  read: number
  total: number
  error?: string
}

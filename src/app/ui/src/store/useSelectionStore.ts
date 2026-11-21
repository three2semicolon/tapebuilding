/**
 * Zustand store for UI state: track selection, clipboard, and modal state.
 */

import { create } from 'zustand'

export interface SelectedTrack {
  path: string
  artist: string
  title: string
  album: string
  length: number
  playlist?: string
}

interface SelectionState {
  selected: Set<string>
  playlistContext: string | null   // which playlist the selection is scoped to
  setSelection: (paths: string[]) => void
  addSelection: (paths: string[]) => void
  removeSelection: (paths: string[]) => void
  toggleSelection: (path: string) => void
  clearSelection: () => void
  setPlaylistContext: (playlist: string | null) => void
  // clipboard
  clipboard: SelectedTrack[]
  setClipboard: (tracks: SelectedTrack[]) => void
  // modal
  openModal: string | null
  setOpenModal: (id: string | null) => void
}

export const useSelectionStore = create<SelectionState>((set) => ({
  selected: new Set(),
  playlistContext: null,
  setSelection: (paths) => set({ selected: new Set(paths) }),
  addSelection: (paths) =>
    set((s) => {
      const next = new Set(s.selected)
      paths.forEach((p) => next.add(p))
      return { selected: next }
    }),
  removeSelection: (paths) =>
    set((s) => {
      const next = new Set(s.selected)
      paths.forEach((p) => next.delete(p))
      return { selected: next }
    }),
  toggleSelection: (path) =>
    set((s) => {
      const next = new Set(s.selected)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return { selected: next }
    }),
  clearSelection: () => set({ selected: new Set() }),
  setPlaylistContext: (playlist) => set({ playlistContext: playlist }),
  clipboard: [],
  setClipboard: (tracks) => set({ clipboard: tracks }),
  openModal: null,
  setOpenModal: (id) => set({ openModal: id }),
}))

export const useSelectedPaths = () => useSelectionStore((s) => s.selected)
export const useSelectionCount = () => useSelectionStore((s) => s.selected.size)
export const usePlaylistContext = () => useSelectionStore((s) => s.playlistContext)

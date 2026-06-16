import { create } from 'zustand'

interface ConfigStore {
  accConnected: boolean
  ajoConnected: boolean
  accLogin: string | null
  ajoOrgId: string | null
  ajoSandboxName: string | null
  setAccConnected: (login: string) => void
  setAccDisconnected: () => void
  setAjoConnected: (orgId: string, sandboxName: string) => void
  setAjoDisconnected: () => void
}

export const useConfigStore = create<ConfigStore>((set) => ({
  accConnected: false,
  ajoConnected: false,
  accLogin: null,
  ajoOrgId: null,
  ajoSandboxName: null,
  setAccConnected: (login) => set({ accConnected: true, accLogin: login }),
  setAccDisconnected: () => set({ accConnected: false, accLogin: null }),
  setAjoConnected: (orgId, sandboxName) => set({ ajoConnected: true, ajoOrgId: orgId, ajoSandboxName: sandboxName }),
  setAjoDisconnected: () => set({ ajoConnected: false, ajoOrgId: null, ajoSandboxName: null }),
}))

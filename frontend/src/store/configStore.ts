import { create } from 'zustand'

interface ConfigStore {
  accConnected: boolean
  ajoConnected: boolean
  accLogin: string | null
  ajoOrgId: string | null
  ajoSandboxName: string | null
  setAccConnected: (login: string) => void
  setAjoConnected: (orgId: string, sandboxName: string) => void
}

export const useConfigStore = create<ConfigStore>((set) => ({
  accConnected: false,
  ajoConnected: false,
  accLogin: null,
  ajoOrgId: null,
  ajoSandboxName: null,
  setAccConnected: (login) => set({ accConnected: true, accLogin: login }),
  setAjoConnected: (orgId, sandboxName) => set({ ajoConnected: true, ajoOrgId: orgId, ajoSandboxName: sandboxName }),
}))

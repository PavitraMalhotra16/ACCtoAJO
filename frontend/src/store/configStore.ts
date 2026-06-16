import { create } from 'zustand'
import { getConnectionsStatus } from '../api/client'

interface ConfigStore {
  accConnected: boolean
  ajoConnected: boolean
  accLogin: string | null
  ajoOrgId: string | null
  ajoSandboxName: string | null
  setAccConnected: (login: string) => void
  setAjoConnected: (orgId: string, sandboxName: string) => void
  fetchStatus: () => Promise<void>
}

export const useConfigStore = create<ConfigStore>((set) => ({
  accConnected: false,
  ajoConnected: false,
  accLogin: null,
  ajoOrgId: null,
  ajoSandboxName: null,
  setAccConnected: (login) => set({ accConnected: true, accLogin: login }),
  setAjoConnected: (orgId, sandboxName) => set({ ajoConnected: true, ajoOrgId: orgId, ajoSandboxName: sandboxName }),
  fetchStatus: async () => {
    try {
      const status = await getConnectionsStatus()
      set({
        accConnected: status.sourceAuthenticated,
        accLogin: status.sourceLoginId,
        ajoConnected: status.destinationAuthenticated,
        ajoOrgId: status.destinationOrgId,
        ajoSandboxName: status.destinationSandboxName,
      })
    } catch {
      // backend not reachable, stay logged out
    }
  },
}))

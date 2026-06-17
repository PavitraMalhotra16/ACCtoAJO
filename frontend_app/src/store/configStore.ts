import { create } from 'zustand'
import { persist } from 'zustand/middleware'

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

export const useConfigStore = create<ConfigStore>()(
  persist(
    (set) => ({
      accConnected: false,
      ajoConnected: false,
      accLogin: null,
      ajoOrgId: null,
      ajoSandboxName: null,
      setAccConnected: (login) => set({ accConnected: true, accLogin: login }),
      setAccDisconnected: () => set({ accConnected: false, accLogin: null }),
      setAjoConnected: (orgId, sandboxName) => set({ ajoConnected: true, ajoOrgId: orgId, ajoSandboxName: sandboxName }),
      setAjoDisconnected: () => set({ ajoConnected: false, ajoOrgId: null, ajoSandboxName: null }),
    }),
    {
      name: 'acc-ajo-connection-state',
      // only persist connection status and identity — never credentials
      partialize: (state) => ({
        accConnected: state.accConnected,
        accLogin: state.accLogin,
        ajoConnected: state.ajoConnected,
        ajoOrgId: state.ajoOrgId,
        ajoSandboxName: state.ajoSandboxName,
      }),
    }
  )
)

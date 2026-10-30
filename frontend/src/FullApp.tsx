import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { JobTrackerProvider } from '@/lab/JobTracker'
import { LabProvider } from '@/lab/LabProvider'
import { ApiError } from '@/lib/api'
import App from './App'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 1,
    },
  },
})

/** The full site: landing plus the shared lab (no login; the backend picks the workspace). */
export default function FullApp() {
  return (
    <QueryClientProvider client={queryClient}>
      <LabProvider>
        <JobTrackerProvider>
          <App />
        </JobTrackerProvider>
      </LabProvider>
    </QueryClientProvider>
  )
}

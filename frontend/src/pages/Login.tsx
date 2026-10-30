import { Navigate } from 'react-router-dom'

/** Obsolete: the lab is public and has no login. Kept only so old imports keep compiling;
 * the router already sends this path to /app. Safe to delete. */
export default function LegacyAccountPage() {
  return <Navigate to="/app" replace />
}

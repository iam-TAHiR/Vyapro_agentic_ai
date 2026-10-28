import { formatStatusLabel } from '../services/status'

type StatusBadgeProps = { status: string }

export function StatusBadge({ status }: StatusBadgeProps) {
  return <span className="status-badge"><span aria-hidden="true">●</span> {formatStatusLabel(status)}</span>
}

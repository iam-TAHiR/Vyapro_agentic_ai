import { useI18n } from '../services/i18n'
type EmptyStateProps = { title: string; message: string }
export function EmptyState({ title, message }: EmptyStateProps) {
  const { t } = useI18n()
  return <section className="state-panel"><h2>{t(title)}</h2><p>{t(message)}</p></section>
}

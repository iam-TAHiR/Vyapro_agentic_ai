import { useI18n } from '../services/i18n'
type ErrorStateProps = { message: string; onRetry: () => void }
export function ErrorState({ message, onRetry }: ErrorStateProps) {
  const { t } = useI18n()
  return <section className="state-panel state-error" role="alert"><h2>{t('Data could not be loaded')}</h2><p>{t(message)}</p><button type="button" onClick={onRetry}>{t('Try again')}</button></section>
}

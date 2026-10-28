import { useI18n } from '../services/i18n'
export function LoadingSkeleton() {
  const { t } = useI18n()
  return <div className="skeleton" aria-label={t('Loading orders')} role="status"><span>{t('Loading orders…')}</span><i /><i /><i /></div>
}

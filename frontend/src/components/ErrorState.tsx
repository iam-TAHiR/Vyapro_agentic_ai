type ErrorStateProps = { message: string; onRetry: () => void }
export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return <section className="state-panel state-error" role="alert"><h2>Orders could not be shown</h2><p>{message}</p><button type="button" onClick={onRetry}>Try development fixtures again</button></section>
}

export function VyaproBrand({ href, workspace }: { href: string; workspace: string }) {
  return <a className="brand" href={href} aria-label={`Vyapro ${workspace} home`}>
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
      <path className="brand-mark-field" d="M16 2.5 28.5 9.3v13.4L16 29.5 3.5 22.7V9.3L16 2.5Z" />
      <path className="brand-mark-v" d="m9 10 7 12 7-12" />
      <circle className="brand-mark-node" cx="16" cy="8.5" r="1.35" />
    </svg>
    <span className="brand-name">Vyapro</span>
    <span className="brand-workspace">{workspace}</span>
  </a>
}

export function Mark({ size = 22 }: { size?: number }) {
  return (
    <svg className="mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect x="2" y="4" width="8" height="24" fill="#e0b15a" />
      <rect x="12" y="4" width="8" height="24" fill="#3ec4b2" />
      <rect x="22" y="4" width="8" height="24" fill="#e36d7a" />
    </svg>
  )
}

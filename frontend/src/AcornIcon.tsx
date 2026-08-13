type AcornIconProps = {
  size?: number
  className?: string
}

function AcornIcon({ size = 18, className }: AcornIconProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M17.2 4.8c1.2-.9 2.6-1.2 4.3-.8-.7.7-1.1 1.5-1.2 2.4-.2 1 .1 1.9.7 2.7" stroke="#6f3f12" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M7.1 13.8c.4-5.2 4.2-8.3 9.1-8.3 4.8 0 8.4 3.1 8.8 8.3H7.1Z" fill="#8b4f18" />
      <path d="M8.9 11.4c1.7-2.8 4.2-4 7.3-4 3.2 0 5.6 1.2 7.1 4-.7-.3-1.6-.5-2.6-.5-1.4 0-2.5.4-3.5 1.1-.9-.7-2-1.1-3.3-1.1-1.2 0-2.3.4-3.2 1.1-.5-.3-1.1-.5-1.8-.6Z" fill="#b06a25" />
      <path d="M6.5 13.2c0-1 .8-1.8 1.8-1.8h15.4c1 0 1.8.8 1.8 1.8v.9c0 1-.8 1.8-1.8 1.8H8.3c-1 0-1.8-.8-1.8-1.8v-.9Z" fill="#6f3f12" />
      <path d="M8.5 15.4c.6 7.4 3.6 12.4 7.5 12.4s6.9-5 7.5-12.4h-15Z" fill="#c97923" />
      <path d="M11.5 16.7c.5 4.4 2.1 7.8 4.5 9.8 2.4-2 4-5.4 4.5-9.8h-9Z" fill="#e89a38" opacity=".85" />
      <path d="M11.1 14.1h.1M15.8 14.1h.1M20.5 14.1h.1" stroke="#d59a5a" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M13.3 22.1c.6 1.3 1.4 2.4 2.7 3.3" stroke="#ffd08a" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  )
}

export default AcornIcon

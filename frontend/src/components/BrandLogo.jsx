import ctiLogo from '../assets/cti-logo.png'

export default function BrandLogo({ className = '', alt = 'CTI' }) {
  return <img src={ctiLogo} alt={alt} className={`brand-logo ${className}`.trim()} />
}

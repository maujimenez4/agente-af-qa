import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Icon, type IconName } from '../Icon/index.ts'
import styles from './Button.module.css'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'lg' | 'md' | 'sm'

type NativeProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'>

export interface ButtonProps extends NativeProps {
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: IconName
  children: ReactNode
}

function classes(variant: ButtonVariant, size: ButtonSize, extra?: string, iconOnly = false): string {
  return [styles.button, styles[variant], styles[size], iconOnly ? styles.iconOnly : undefined, extra]
    .filter(Boolean)
    .join(' ')
}

const ICON_SIZE: Record<ButtonSize, number> = { lg: 18, md: 18, sm: 14 }

// Botón del sistema (lienzo: .btn .pri/.sec, .sm, .mini). Desactivado con `disabled` nativo.
export function Button({ variant = 'secondary', size = 'lg', icon, className, type = 'button', children, ...rest }: ButtonProps) {
  return (
    <button type={type} className={classes(variant, size, className)} {...rest}>
      {icon && <Icon name={icon} size={ICON_SIZE[size]} />}
      {children}
    </button>
  )
}

export interface IconButtonProps extends NativeProps {
  icon: IconName
  /** Nombre accesible obligatorio: el botón no tiene texto visible. */
  label: string
  variant?: ButtonVariant
  size?: ButtonSize
}

// Botón solo con icono (lienzo: .ic, enviar, detener, cerrar).
export function IconButton({
  icon,
  label,
  variant = 'ghost',
  size = 'md',
  className,
  type = 'button',
  ...rest
}: IconButtonProps) {
  return (
    <button type={type} className={classes(variant, size, className, true)} aria-label={label} {...rest}>
      <Icon name={icon} size={ICON_SIZE[size]} />
    </button>
  )
}

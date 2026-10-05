import { forwardRef, useId, type InputHTMLAttributes } from 'react'
import styles from './TextField.module.css'

export interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id' | 'className'> {
  label: string
  /** Error del campo: lo enlaza con aria-describedby y marca aria-invalid. */
  error?: string
}

// Campo de texto con su etiqueta visible (lienzo: inputs de 44 px, borde #93A0AB y radio 10).
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField({ label, error, ...rest }, ref) {
  const id = useId()
  const errorId = `${id}-error`
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      <input
        ref={ref}
        id={id}
        className={styles.input}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        {...rest}
      />
      {error && (
        <p id={errorId} className={styles.error}>
          {error}
        </p>
      )}
    </div>
  )
})

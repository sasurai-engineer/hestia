import { useId } from 'react';

/**
 * The instrument: a slider whose readout is live engine math. The readout
 * doubles as aria-valuetext so a screen reader hears "exit June 2031 —
 * IRR 11.2%", never a bare number.
 */
type RangeFieldProps = {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  format?: (value: number) => string;
};

export function RangeField({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
  format,
}: RangeFieldProps) {
  const id = useId();
  const readout = format === undefined ? String(value) : format(value);
  return (
    <div className="field range-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-valuetext={readout}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <output htmlFor={id} className="range-field__readout">
        {readout}
      </output>
    </div>
  );
}

interface Props {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  colSpan?: boolean;
}

export function FieldInput({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  colSpan,
}: Props) {
  return (
    <div className={colSpan ? "sm:col-span-2" : ""}>
      <label className="block text-xs text-gray-400 mb-1">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
      />
    </div>
  );
}

import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, Save } from "lucide-react";

interface Props {
  title: string;
  icon: ReactNode;
  children: ReactNode;
  onSave?: () => void;
  saving?: boolean;
  defaultOpen?: boolean;
}

export function CollapsibleSection({
  title,
  icon,
  children,
  onSave,
  saving,
  defaultOpen = false,
}: Props) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-3 hover:bg-gray-700/30 transition-colors"
      >
        <div className="flex items-center gap-2 text-sm font-semibold">
          {icon}
          {title}
        </div>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>

      {open && (
        <div className="px-5 pb-4 space-y-4 border-t border-gray-700/50">
          <div className="pt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
            {children}
          </div>
          {onSave && (
            <div className="flex justify-end">
              <button
                type="button"
                onClick={onSave}
                disabled={saving}
                className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-4 py-2 rounded-lg text-sm font-medium"
              >
                <Save size={14} />
                {saving ? "Saving..." : "Save"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

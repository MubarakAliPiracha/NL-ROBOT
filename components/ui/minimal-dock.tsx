'use client';

import React, { useState } from 'react';
import { Home, Search, Mail, Settings, User, Star, Camera } from 'lucide-react';

export interface DockItem {
  id: string;
  icon: React.ReactNode;
  label: string;
  onClick?: () => void;
}

/* Template defaults, kept for drop-in demo use; real pages pass their own items. */
const defaultItems: DockItem[] = [
  { id: 'home', icon: <Home size={20} />, label: 'Home' },
  { id: 'search', icon: <Search size={20} />, label: 'Search' },
  { id: 'mail', icon: <Mail size={20} />, label: 'Mail' },
  { id: 'camera', icon: <Camera size={20} />, label: 'Camera' },
  { id: 'favorites', icon: <Star size={20} />, label: 'Favorites' },
  { id: 'profile', icon: <User size={20} />, label: 'Profile' },
  { id: 'settings', icon: <Settings size={20} />, label: 'Settings' },
];

interface DockItemProps {
  item: DockItem;
  isHovered: boolean;
  onHover: (id: string | null) => void;
}

const DockItemComponent: React.FC<DockItemProps> = ({ item, isHovered, onHover }) => {
  return (
    <div className="group relative" onMouseEnter={() => onHover(item.id)} onMouseLeave={() => onHover(null)}>
      <button
        type="button"
        aria-label={item.label}
        className={`
          relative flex h-11 w-11 items-center justify-center
          border border-line bg-surfaceAlt
          cursor-pointer transition-all duration-300 ease-out
          ${isHovered ? '-translate-y-1 scale-110 border-brand/60 bg-brand/10' : 'hover:-translate-y-0.5 hover:scale-105 hover:bg-brand/5'}
        `}
        onClick={item.onClick}
        style={{
          boxShadow: isHovered ? '0 4px 24px 0 rgb(62 207 142 / 0.15)' : undefined,
          transitionProperty: 'box-shadow, transform, background, border-color',
        }}
      >
        <div className={`text-fg transition-all duration-300 ${isHovered ? 'scale-105 text-brand' : ''}`}>
          {item.icon}
        </div>
      </button>

      {/* Tooltip */}
      <div
        className={`
          pointer-events-none absolute -top-10 left-1/2 -translate-x-1/2
          whitespace-nowrap border border-line bg-app px-2.5 py-1
          text-xs text-fg transition-all duration-200
          ${isHovered ? 'translate-y-0 opacity-100' : 'translate-y-1 opacity-0'}
        `}
      >
        {item.label}
        <div className="absolute left-1/2 top-full -translate-x-1/2">
          <div className="h-2 w-2 rotate-45 border-b border-r border-line bg-app" />
        </div>
      </div>
    </div>
  );
};

/**
 * macOS-style dock, restyled for the terminal theme (flat panes, one accent,
 * no gradients) and embeddable: the original template rendered its own
 * full-screen demo page; here the page supplies items and placement.
 */
const MinimalistDock: React.FC<{ items?: DockItem[]; className?: string }> = ({
  items = defaultItems,
  className = '',
}) => {
  const [hoveredItem, setHoveredItem] = useState<string | null>(null);

  return (
    <div
      className={`
        flex items-end gap-3 border border-line bg-surface/90 px-5 py-3
        backdrop-blur-xl transition-all duration-500 ease-out
        ${hoveredItem ? 'scale-105' : ''}
        ${className}
      `}
    >
      {items.map((item) => (
        <DockItemComponent key={item.id} item={item} isHovered={hoveredItem === item.id} onHover={setHoveredItem} />
      ))}
    </div>
  );
};

export default MinimalistDock;

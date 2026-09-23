import React from 'react';
import { Construction } from 'lucide-react';

interface PlaceholderPageProps {
  title: string;
  description: string;
}

export const PlaceholderPage: React.FC<PlaceholderPageProps> = ({ title, description }) => (
  <div className="px-6 lg:px-12 py-12">
    <h1 className="text-3xl md:text-4xl font-normal tracking-tight mb-2">{title}</h1>
    <div className="glass-card mt-10 p-16 rounded-3xl text-center flex flex-col items-center justify-center border border-white/10">
      <Construction className="w-12 h-12 text-neutral-500 mb-4" />
      <h3 className="text-lg font-medium mb-2">Coming soon</h3>
      <p className="text-neutral-400 text-sm max-w-sm">{description}</p>
    </div>
  </div>
);

import {
  BookOpen,
  BrainCircuit,
  Briefcase,
  Compass,
  GitCompareArrows,
  ListChecks,
  Search,
  Sparkles,
} from "./icons";
import type { LucideIcon } from "lucide-react";

// Server-side tool names emitted by agent/catalog_wiki_tools.py. We map to a
// curated lucide icon so the timeline reads like an action, not a debug log.
// Anything unknown gets the generic Sparkles icon.
const TOOL_ICONS: Record<string, LucideIcon> = {
  search_programs: Search,
  retrieve_program_candidates: Search,
  get_program: BookOpen,
  get_program_section: BookOpen,
  get_curriculum: ListChecks,
  list_subjects: ListChecks,
  get_subject: ListChecks,
  compare_programs: GitCompareArrows,
  list_areas: Compass,
  list_levels: Compass,
  faq_lookup: BrainCircuit,
  career_paths: Briefcase,
};

interface ToolIconProps {
  name: string;
  className?: string;
}

export function ToolIcon({ name, className }: ToolIconProps) {
  const Icon = TOOL_ICONS[name] ?? Sparkles;
  return <Icon className={className} aria-hidden="true" />;
}

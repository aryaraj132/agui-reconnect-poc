export interface ComponentDefinition {
  type: string;
  label: string;
  icon: string;
  defaultContent: string;
  defaultStyles: Record<string, string>;
}

export const TEMPLATE_COMPONENTS: ComponentDefinition[] = [
  {
    type: "header",
    label: "Header",
    icon: "H",
    defaultContent: "Your Header Title",
    defaultStyles: {
      "background-color": "#333",
      color: "#fff",
      padding: "20px",
    },
  },
  {
    type: "body",
    label: "Body",
    icon: "B",
    defaultContent: "Your body text goes here. Write something compelling.",
    defaultStyles: { padding: "20px", "font-size": "14px" },
  },
  {
    type: "footer",
    label: "Footer",
    icon: "F",
    defaultContent: "\u00a9 2026 Your Company. All rights reserved.",
    defaultStyles: {
      "background-color": "#f5f5f5",
      color: "#999",
      padding: "20px",
    },
  },
  {
    type: "cta",
    label: "CTA",
    icon: "C",
    defaultContent: "Click Here",
    defaultStyles: {
      "background-color": "#007bff",
      color: "#fff",
      padding: "14px 28px",
    },
  },
  {
    type: "image",
    label: "Image",
    icon: "I",
    defaultContent: "https://via.placeholder.com/600x200",
    defaultStyles: { "text-align": "center" },
  },
  {
    type: "divider",
    label: "Divider",
    icon: "\u2014",
    defaultContent: "",
    defaultStyles: { padding: "10px 20px" },
  },
  {
    type: "spacer",
    label: "Spacer",
    icon: "\u2195",
    defaultContent: "",
    defaultStyles: { height: "20px" },
  },
  {
    type: "social_links",
    label: "Social Links",
    icon: "@",
    defaultContent: "Follow us: Twitter | LinkedIn | GitHub",
    defaultStyles: { "text-align": "center", padding: "20px" },
  },
  {
    type: "text_block",
    label: "Text Block",
    icon: "T",
    defaultContent: "A rich text content block for detailed information.",
    defaultStyles: { padding: "20px", "font-size": "14px" },
  },
  {
    type: "columns",
    label: "Columns",
    icon: "||",
    defaultContent: "Column 1 content | Column 2 content",
    defaultStyles: { padding: "20px" },
  },
];

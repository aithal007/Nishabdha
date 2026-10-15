# Frontend references and licenses

The local Button, Dialog, and AlertDialog wrappers adapt the source-owned component approach and Radix composition patterns of [shadcn/ui](https://github.com/shadcn-ui/ui). The app uses its own banking theme and local CSS. These files are editable application source, not an installed hosted design service.

shadcn/ui — MIT License — Copyright (c) 2023 shadcn

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

The design workflow was informed by [LibreUIUX](https://github.com/Ormus-Solutions/LibreUIUX-Claude-Code), specifically its design-context loop and modern-web-app typography, spacing, semantic-color, and accessibility guidance. No LibreUIUX marketplace, hooks, or Claude runtime is installed in the application.

[CopilotKit](https://github.com/CopilotKit/CopilotKit) and its AG-UI client are actual application dependencies. The policy assistant uses the headless React hook/context and an HTTP agent backed by the read-only FastAPI policy stream. All npm dependencies retain their package-specific license notices in the installed distribution. The lockfile records exact resolved versions.

Inter font files are distributed under the SIL Open Font License; the notice is retained in [`licenses/Inter-OFL.txt`](licenses/Inter-OFL.txt).

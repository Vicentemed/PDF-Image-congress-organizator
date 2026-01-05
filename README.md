# PDF & Image Certificate Organizer

A desktop application designed to automatically organize academic certificates, diplomas, and documents. It processes **PDFs** and **Image files** (JPG, PNG, etc.), extracting the **recipient's name** and the **event year** using advanced Text Extraction and OCR (Optical Character Recognition).

Files are automatically moved into a structured directory tree: `Destination/{Year}/{Name}/`.

## Features

-   **Format Support**:
    -   📄 **PDFs**: Handles both text-selectable PDFs (native extraction) and Scanned PDFs (OCR).
    -   🖼️ **Images**: Supports JPG, PNG, BMP, TIFF direct processing.
-   **Smart Extraction**:
    -   Extracts **Dates** (Years) from Spanish text (e.g., "Expedido el 12 de Enero de 2024").
    -   Extracts **Names** using keyword context (e.g., "Otorga a", "Certifica a", "Reviewer Certificate").
    -   **English Support**: Works with standard English certificate formats.
    -   **Fallback Strategy**: If no name is found in the text, it attempts to use the **Filename**.
-   **Local OCR**: Uses **Tesseract-OCR** for high-accuracy text recognition on images.
-   **Portable Poppler**: Supports including a local Poppler binary for easy deployment.
-   **GUI**: Simple and easy-to-use Tkinter interface.

## Installation

### 1. Requirements

Make sure you have [Python 3.x](https://www.python.org/downloads/) installed. Then install the Python dependencies:

```bash
pip install -r requirements.txt
```

### 2. External Tools (OCR)

This app relies on two external tools to "read" images:

#### A. Tesseract-OCR (Required)
1.  Download and install **Tesseract** for Windows (e.g., from [UB-Mannheim](https://github.com/UB-Mannheim/tesseract/wiki)).
2.  Install the **Spanish Language Pack**:
    *   Download `spa.traineddata` from [tessdata_best](https://github.com/tesseract-ocr/tessdata_best/blob/main/spa.traineddata).
    *   Place it in `C:\Program Files\Tesseract-OCR\tessdata\`.

#### B. Poppler (Required for Scanned PDFs)
The application expects a local `poppler` folder or a system-installed version.
1.  Download the latest poppler Release for Windows.
2.  Extract it into the project folder so the structure looks like:
    ```
    /project-folder/
       pdf_organizer.py
       poppler-xx.xx.x/
          Library/
             bin/ (contains pdftoppm.exe, etc.)
    ```
    *The app will automatically detect it.*

## Usage

1.  Run the application:
    ```bash
    python pdf_organizer.py
    ```
2.  Select the **Source Folder** (containing your unorganized files).
3.  Select the **Destination Folder** (where organized subfolders will be created).
4.  Click **"Procesar Archivos"**.
5.  Watch the log window for progress and any files that require manual review (marked as "Desconocido").

## Troubleshooting

-   **"ModuleNotFoundError"**: Run `pip install -r requirements.txt`.
-   **"Tesseract not found"**: Ensure Tesseract is installed at `C:\Program Files\Tesseract-OCR\tesseract.exe` or add it to your PATH.
-   **"Unable to get page count"**: This allows means Poppler is missing. Check the `poppler` folder structure.

## License

This project is open-source. Feel free to modify and adapt it to your needs.

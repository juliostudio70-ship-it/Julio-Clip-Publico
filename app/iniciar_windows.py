"""Entrada de doble clic; no requiere Python instalado ni permisos de administrador."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from comprobar_windows import preflight
import server

def main():
    try:
        print('Julio Clip: verificando las herramientas incluidas...', flush=True)
        preflight()
        print('Herramientas listas. Se abrirá la interfaz local en el navegador.', flush=True)
        print('Mantén esta ventana abierta. Control + C detiene Julio Clip.', flush=True)
        server.main()
        return 0
    except ValueError as error:
        print('ERROR: ' + str(error), flush=True)
    except OSError as error:
        if getattr(error, 'winerror', None) == 10048 or error.errno == 10048:
            print('El puerto 8765 está ocupado. Cierra la otra instancia antes de abrir Julio Clip otra vez.', flush=True)
        else:
            print('No se pudo iniciar el programa. Revisa espacio y permisos de tu carpeta de usuario.', flush=True)
    return 1

if __name__ == '__main__':
    sys.exit(main())

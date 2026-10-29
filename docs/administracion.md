# Administración

[← Volver al manual](README.md)

## Usuarios y permisos

**Usuarios** (con el permiso del módulo).

### Crear un usuario

**Nuevo usuario:** nombre, usuario o correo y contraseña. Si dejas la contraseña vacía se genera una **temporal**, que se muestra una sola vez: cópiala y dásela a la persona. Al entrar, el sistema le pide cambiarla.

### La ficha del usuario

- **Sucursales:** en cuáles puede trabajar. Solo puedes asignar sucursales a las que tú perteneces.
- **Accesos:** marca cada módulo y lo que puede hacer en él: **Ver**, **Crear**, **Editar**, **Eliminar** y, según el módulo, permisos especiales:
  - **Exportar** (reportes).
  - **Límite de crédito** (clientes): asignar o cambiar el crédito de un cliente.
  - **Precios** (productos): precios, listas de precios, paquetes y membresías.
  - **Solo sus citas** (citas): ver solo las citas asignadas a la persona o que ella agendó.
  
  Solo puedes dar permisos que tú tienes.
- **Suspender:** la persona no puede entrar y sus sesiones se cierran; su información se conserva.
- **Resetear contraseña:** genera una contraseña temporal y cierra sus sesiones.
- **Cerrar sus sesiones:** tendrá que volver a entrar en todos sus dispositivos.
- Su historial de accesos y de cambios.

Los usuarios se eliminan y restauran desde la lista; sus documentos y movimientos se conservan.

## Sucursales

**Sucursales → Nueva sucursal:** nombre, **código** (letras y números, hasta 10; aparece en los folios, por ejemplo `SUC1-000123`), teléfono y dirección. Cuando ya se emitieron folios con un código, ya no se puede cambiar.

En la sucursal, **Usuarios asignados**: solo ellos pueden elegirla al entrar. **Asignar usuario** y quitar (no se puede quitar a alguien con trabajo abierto ahí, como una caja ocupada).

No se puede eliminar una sucursal con productos en existencia, cajas abiertas, conteos abiertos o traspasos en camino. Su historial se conserva y se puede restaurar.

## Configuración

**Configuración** (con el permiso del módulo):

- **Logo:** JPG, PNG o WebP de hasta 5 MB. Aparece en los tickets, las recetas, las cotizaciones, el catálogo público y como ícono de la app instalada. **Cambiar logo** y **Quitar logo**.
- **Giro del negocio:** Comercio, Belleza, Salud o Música. Define qué módulos aparecen y cómo se llaman las cosas (ver [Conceptos básicos](README.md#conceptos-básicos)). Al elegirlo, si todavía no hay campos propios, se sugieren algunos típicos del giro, que puedes editar o quitar.
- **Datos adicionales del cliente:** campos propios del negocio (texto, texto largo, número, fecha, lista de opciones o sí/no; obligatorios o no). Se piden al registrar o editar un cliente.
- **Datos de cada cita:** lo mismo para las citas o eventos (por ejemplo lugar, invitados, hora de montaje). Solo en giros que usan citas.
- **Recordatorios por WhatsApp:** el texto del mensaje. Puedes usar `{cliente}`, `{fecha}`, `{hora}`, `{sucursal}` y `{servicios}`. Vacío usa el de la app.
- **Expediente clínico** (giro Salud): encabezado de las recetas y aviso de privacidad.
- **WhatsApp del catálogo:** el número (con lada del país) al que llegan los pedidos del catálogo público.

## Catálogo público

Es una página para tus clientes, **sin iniciar sesión**, en la dirección de Osmi terminada en `/catalog` (Configuración muestra el enlace para copiarlo y compartirlo).

- Muestra los productos con existencia y los servicios, con sus imágenes y precios, y el logo del negocio.
- La existencia no se muestra exacta: aparece "Última pieza" o "Últimas piezas" cuando quedan pocas.
- El cliente arma su pedido y lo envía por WhatsApp al número de Configuración. **No se registra nada en el sistema**; es un mensaje para apartar, que el negocio atiende y cobra en el punto de venta.

## Calendarios del equipo

**Calendario** sirve para organizar el trabajo interno (entregas, inventarios, juntas), aparte de las citas con clientes:

- **Nuevo calendario** con nombre, descripción y color.
- **Nuevo evento:** título, inicio y fin, lugar, cliente (opcional) y descripción.
- **Compartir:** agrega personas con permiso **Puede editar** (crea, cambia y elimina eventos) o **Solo lectura**.
- Eliminar un calendario elimina sus eventos para todos con quienes se compartió.

## Formas de pago y cajas

Se administran desde **Cajas**; ver [Cajas y corte de caja](cajas.md#formas-de-pago).

# Manual de Osmi

Osmi es un sistema de punto de venta y administración para negocios con una o varias sucursales: ventas, cajas, inventario, compras, clientes, cotizaciones, citas o eventos, gastos, reportes y, para consultorios, expediente clínico.

Este manual explica cómo usar cada parte del sistema.

## Contenido

| Tema | Para quién |
|---|---|
| [Primeros pasos](primeros-pasos.md): entrar, elegir sucursal, tu perfil, instalar la app | Todos |
| [Punto de venta](punto-de-venta.md): cobrar, formas de pago, crédito, apartados, descuentos | Cajeros |
| [Vender sin conexión](venta-sin-conexion.md): seguir cobrando cuando se cae internet | Cajeros |
| [Ventas](ventas.md): consultar ventas, entregas, cobros pendientes, devoluciones | Cajeros y encargados |
| [Cajas y corte de caja](cajas.md): ocupar una caja, entradas, retiros, corte | Cajeros y supervisores |
| [Clientes](clientes.md): alta, crédito, abonos, compras, paquetes y membresías | Recepción, caja |
| [Cotizaciones](cotizaciones.md): cotizar, enviar, convertir en venta | Ventas |
| [Citas y eventos](citas-y-eventos.md): agendar, servicios, anticipos, recordatorios | Recepción |
| [Expediente clínico](expediente-clinico.md): consultas, recetas, estudios, odontograma | Médicos y dentistas |
| [Productos](productos.md): productos, servicios, kits, imágenes, catálogos, listas de precios | Encargados |
| [Inventario](inventario.md): existencias, ajustes, compras, proveedores, traspasos, conteos | Almacén y encargados |
| [Gastos](gastos.md): registrar lo que se paga y lo que se debe | Encargados |
| [Promociones](promociones.md): descuentos automáticos en el punto de venta | Encargados |
| [Reportes](reportes.md): el día de hoy y el catálogo de reportes | Encargados y dueños |
| [Administración](administracion.md): usuarios y permisos, sucursales, configuración, catálogo público | Administradores |

## Conceptos básicos

**Sucursal.** Cada sucursal tiene su propio inventario, sus cajas y sus folios (por ejemplo `SUC1-000123`). Los productos, los clientes y los proveedores se comparten entre todas. Si trabajas en varias sucursales, al entrar eliges en cuál vas a trabajar y todo lo que registres queda en ella.

**Caja.** Para cobrar, recibir abonos o sacar dinero hay que *ocupar* una caja de la sucursal. Una caja la ocupa una sola persona a la vez. Al terminar el turno se hace el corte, que la deja libre.

**Módulos y permisos.** Cada persona ve solo los módulos que le asignaron, y dentro de cada uno solo puede hacer lo que su permiso le deja (ver, crear, editar, eliminar y algunos especiales). Si no ves un botón o un módulo que necesitas, pídelo a un administrador.

**Giro del negocio.** En Configuración se elige el giro: Comercio, Belleza, Salud o Música. El giro decide qué módulos aparecen y cómo se llaman las cosas:

| Giro | Citas se llaman | Clientes se llaman | Módulos propios |
|---|---|---|---|
| Comercio | (no usa citas) | Clientes | — |
| Belleza | Citas | Clientes | — |
| Salud | Consultas | Pacientes | Expediente clínico |
| Música | Eventos | Clientes | — |

En este manual se usan las palabras *citas* y *clientes*; en tu pantalla verás las de tu giro.

**Historial.** Casi todo lo que cambia queda registrado con quién lo hizo y cuándo: ventas, clientes, productos, citas, cortes. Lo que se elimina normalmente se puede restaurar, y lo que mueve dinero o existencias no se borra: se corrige con un movimiento nuevo (una devolución, un ajuste, una anulación).

**Idioma.** La app está en español y en inglés; el cambio de idioma está al pie del menú.

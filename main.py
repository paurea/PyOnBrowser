import ast
import sys
import io
import os
import argparse
import json

emulateDir=""

class FuncVisitor (ast.NodeVisitor):
	def __init__ (self, node):
		self.local_vars = []
		self.global_vars = []
		self.posargs, self.defaults = [], []
		self.visit (node)
	def get_local_vars (self):
		return self.local_vars
	def get_gl_vars (self):
		return (self.global_vars, self.local_vars)
	def get_pd_args (self):
		return (self.posargs, self.local_vars)
	def visit_Assign (self, node):
		targets = node.targets
		for target in targets:
			if (isinstance (target, ast.Subscript)):
				self.visit (target.value)
			elif (not isinstance (target, ast.Tuple)):
				if (target.id not in self.global_vars):
					self.local_vars.append (target.id)
	def visit_Global (self, node):
		for name in node.names:
			self.global_vars.append (name)
	def visit_arguments (self, node):
		args, defaults = node.args, node.defaults
		self.posargs = (arg.arg for arg in args)
		self.defaults = defaults.copy ()

	def visit_FunctionDef (self, node):
		self.visit (node.args)
		for stmt in node.body:
			self.visit (stmt)

class Visitor (ast.NodeVisitor):
	def __init__ (self, ostream, scope = '__scope__', init = '', subfile = None):
		self.ostream = ostream
		self.aug = False
		self.in_exp = False
		self.global_vars = []
		self.scope = scope
		self.indent_level = 0;
		self.exp = 0
		self.curr_lineno = 0
		self.jslineno = 1284 + 8 - 1 - 15
		self.linemap = {}
		self.write (init)
		if (subfile is not None):
			try :
				f = open (subfile)
				self.substitute = json.load (f)
			except Exception as e:
				print (e)
				raise Exception ('Subfile doesnt exist')
		else:
			self.substitute = None
	# Literals
	def visit_Num (self, node):
		if (isinstance (node.n, int)):
			self.ostream.write (f'(new __PyInt__ ({node.n}))')
		elif (isinstance (node.n, float)):
			self.ostream.write (f'(new __PyFloat__ ({node.n}))')
		elif (isinstace (node.n, complex)):
			pass

	def visit_Str (self, node):
		self.ostream.write (f'(new __PyStr__ (\'{node.s}\'))')

	def visit_NameConstant (self, node):
		self.ostream.write (f'__Py{node.value}__')

	def visit_List (self, node):
		# To indicate that an expression in expected inside the parameters of pylist,
		# in_exp is set to True. It is later reseted to it's original value. This is
		# needed only to make sure that calls aren't terminated by a ';' inside an expression.
		prev = self.in_exp
		self.in_exp = True

		elts, ctx = node.elts, node.ctx
		self.ostream.write ('new __PyList__ ([')
		for elt in elts:
			self.visit (elt)
			self.ostream.write (', ')
		self.ostream.write ('])')
		self.in_exp = prev

	def visit_Tuple (self, node):
		prev = self.in_exp
		self.in_exp = True

		elts, ctx = node.elts, node.ctx
		self.ostream.write ('new __PyTuple__ ([')
		for elt in elts:
			self.visit (elt)
			self.ostream.write (', ')
		self.ostream.write ('])')

		self.in_exp = prev

	def visit_Dict (self, node):
		keys, values = node.keys, node.values
		self.ostream.write ('new __PyDict__ (')
		prev_in_exp = self.in_exp
		self.in_exp = True

		self.ostream.write ('[')
		for k in keys:
			self.visit (k)
			self.ostream.write (', ')
		self.ostream.write (']')

		self.ostream.write (', ')

		self.ostream.write ('[')
		for v in values:
			self.visit (v)
			self.ostream.write (', ')
		self.ostream.write (']')

		self.ostream.write (')')
		self.in_exp = prev_in_exp
	# Exprs
	def visit_UnaryOp (self, node):
		prev = self.in_exp
		self.in_exp = True
		op, operand = node.op, node.operand
		self.visit (op)
		self.ostream.write (' (')
		self.visit (operand)
		self.ostream.write (')')
		self.in_exp = prev

	def visit_UAdd (self, node):
		self.ostream.write ('__uadd__')
	def visit_USub (self, node):
		self.ostream.write ('__usub__')

	def visit_BinOp (self, node):
		prev = self.in_exp
		self.in_exp = True
		left, op, right = node.left, node.op, node.right
		self.ostream.write ('(')
		self.visit (op)
		self.ostream.write ('(')
		self.visit (left)
		self.ostream.write (',')
		self.visit (right)
		self.ostream.write ('))')

		self.in_exp = prev

	def visit_Attribute (self, node):
		value, attr, ctx = node.value, node.attr, node.ctx
		self.visit (value)
		if (isinstance (ctx, ast.Store)):
			self.ostream.write (f'''.__setattr__ ('{attr}',  ''')
		else:
			self.ostream.write (f'''.__getattr__ ('{attr}')''')

	def visit_Add (self, node):
		self.ostream.write (f'__{"i" if self.aug else ""}add__')

	def visit_Sub (self, node):
		self.ostream.write (f'__{"i" if self.aug else ""}sub__')

	def visit_Mult (self, node):
		self.ostream.write (f'__{"i" if self.aug else ""}mul__')

	def visit_Div (self, node):
		self.ostream.write (f'__{"i" if self.aug else ""}div__')

	def visit_Name (self, node):
		id = node.id
		self.ostream.write (f'({self.scope}.{id})')

	def visit_Compare (self, node):
		self.in_exp = True;
		left, ops, comparators = node.left, node.ops, node.comparators
		self.ostream.write ('(')
		for op in ops:
			self.visit (op)
			self.ostream.write ('(')
			self.visit (left)
			self.ostream.write (', ')
			self.visit (comparators[0])
			left = comparators[0]
			comparators = comparators[1:]
			self.ostream.write (')')
			self.ostream.write (')')
			self.in_exp = False

	def visit_Call (self, node):
		func, args = node.func, node.args
		if (not self.in_exp):
			self.curr_lineno = node.lineno
			self.write ("")

		# __call__ primitive in 'utils.js' returns the __call__ method from the object.
		# If such a method doesn't exist, it throws a TypeError: object not callable.
		self.ostream.write ('__call__(')
		self.visit (func)
		self.ostream.write (')')
		self.ostream.write ('(')

		prev_in_exp = self.in_exp
		self.in_exp = True

		for arg in args:
			self.visit (arg)
			self.ostream.write (', ')

		# if (len (args) > 0) : self.visit (args[-1])

		self.ostream.write (')')
		self.in_exp = prev_in_exp
		if (not self.in_exp):
			self.write_endline ()


	# Statements
	def visit_Assign (self, node):

		self.curr_lineno = node.lineno
		self.write_lineno ()
		self.write_indent ()

		targets, value = node.targets, node.value
		for target in targets:
			if (isinstance (target, ast.Tuple)):
				prev_in_exp = self.in_exp
				self.in_exp = True
				self.write ('{\n')
				self.indent_level += 1

				self.write ('let vars = [')
				for var in target.elts:
					self.ostream.write (f'\'{var.id}\', ')
				self.write ('];')

				self.write ('let pos = 0;\n')
				self.write ('for (let x of __iter__ (')
				self.visit (value)
				self.ostream.write (')) {\n')
				self.indent_level += 1
				self.write ('if (pos >= vars.length) {\n')
				self.indent_level += 1
				self.write ('__callstack__ = new Error ().stack; throw new __PyValueError__ (`too many values to unpack (expected ${vars.length})`)\n')
				self.indent_level -= 1
				self.write ('}\n')
				self.write (f'{self.scope}[vars[pos]] = x;\n')
				self.write ('pos++;')
				self.write ('}')
				self.indent_level -= 1
				self.write ('if (pos != vars.length) {\n')
				self.indent_level += 1
				self.write ('__callstack__ = new Error ().stack; throw new __PyValueError__ (`not enough values to unpack`)\n')
				self.indent_level -= 1
				self.write ('}\n')

				self.indent_level -= 1
				self.write ('}')
				self.in_exp = prev_in_exp
			else:
				if (isinstance (target, ast.Subscript) or isinstance (target, ast.Attribute)):
					self.visit (target)
					self.visit (value)
					self.ostream.write (')')
				else:
					self.visit (target)
					self.ostream.write (' = ')
					self.visit (value)
				self.write_endline ()


	def visit_AugAssign (self, node):
		target, op, value = node.target, node.op, node.value
		self.visit (target)
		self.ostream.write (' = ')
		prev = self.aug
		self.aug = True
		self.visit (op)
		self.aug = prev
		self.ostream.write (' (')
		self.visit (target)
		self.ostream.write (', ')
		self.visit (value)
		self.ostream.write (')')
		self.write_endline()

	def visit_BoolOp (self, node):
		op, values = node.op, node.values
		self.ostream.write ('__getbool__ (')
		for value in values[:-1]:
			self.ostream.write ('(')
			self.visit (value)
			self.ostream.write (').__bool__ () === __PyTrue__')
			if (isinstance (op, ast.And)):
				self.ostream.write (' && ')
			elif (isinstance (op, ast.Or)):
				self.ostream.write (' || ')

		self.ostream.write ('(')
		self.visit (values[-1])
		self.ostream.write (').__bool__ () === __PyTrue__')

		self.ostream.write (')')

	def visit_Eq (self, _):
		self.ostream.write ('__eq__')
	def visit_NotEq (self, _):
		self.ostream.write ('__neq__')
	def visit_Lt (self, _):
		self.ostream.write ('__lt__')
	def visit_LtE (self, _):
		self.ostream.write ('__le__')
	def visit_Gt (self, _):
		self.ostream.write ('__gt__')
	def visit_GtE (self, _):
		self.ostream.write ('__ge__')
	def visit_Is (self, _):
		self.ostream.write ('__is__')
	def visit_IsNot (self, _):
		self.ostream.write ('__isnot__')
	def visit_Mod (self, _):
		self.ostream.write ('__mod__')
	def visit_And (self, _):
		self.ostream.write ('__and__')
	def visit_In (self, _):
		self.ostream.write ('__in__')
	def visit_NotIn (self, _):
		self.ostream.write ('__notin__')

	def visit_Or (self, _):
		self.ostream.write ('__or__')

	def visit_Subscript (self, node):
		value, slice, ctx = node.value, node.slice, node.ctx
		if (isinstance (ctx, ast.Store)):
			self.ostream.write ('__setitem__ (')
			self.visit (value)
			self.ostream.write (', ')
			self.visit (node.slice)
			self.ostream.write (', ')
		elif (isinstance (ctx, ast.Load)):
			self.ostream.write ('__getitem__ (')
			self.visit (value)
			self.ostream.write (', ')
			self.visit (node.slice)
			self.ostream.write (')')

	def visit_Slice (self, node):
		prev_in_exp = self.in_exp
		self.in_exp = True

		lower, upper, step = node.lower, node.upper, node.step

		self.ostream.write (f'__PySlice__.__call__ (')
		if (lower is None): self.ostream.write ('__PyNone__')
		else: self.visit (lower)
		self.ostream.write (', ')
		if (upper is None): self.ostream.write ('__PyNone__')
		else: self.visit (upper)
		self.ostream.write (', ')
		if (step is None): self.ostream.write ('__PyNone__')
		else: self.visit (step)
		self.ostream.write (')')

		self.in_exp = prev_in_exp

	# Control Flow

	def visit_If (self, node):
		self.curr_lineno = node.lineno
		test, body, orelse = node.test, node.body, node.orelse
		self.write ('if ( (')

		self.in_exp = True
		self.visit (test)
		self.in_exp = False

		self.ostream.write (').__bool__ () === __PyTrue__) {\n')

		self.indent_level += 1
		for stmt in body:
			self.visit (stmt)
		self.indent_level -= 1
		self.write ('}\n')

		self.write ('else {\n')
		for elseif in orelse:
			self.indent_level += 1
			self.visit (elseif)
			self.indent_level -= 1
		self.ostream.write ('}\n')

		# if (len (orelse) > 0):
		# 	self.write ('else {\n')
		# 	self.indent_level += 1
		# 	self.visit (orelse[-1])
		# 	self.indent_level -= 1
		# 	self.write ('}\n')

	def visit_While (self, node):
		test, body = node.test, node.body
		self.write ('while ( (')

		self.in_exp = True
		self.visit (test)
		self.in_exp = False

		self.ostream.write (').__bool__ () === __PyTrue__) {\n')
		self.jslineno += 1

		self.indent ()
		for stmt in body:
			self.visit (stmt)
		self.unindent ()

		self.write ('}\n')
		self.jslineno += 1

	def visit_For (self, node):
		target, iter, body = node.target, node.iter, node.body
		if (not isinstance (target, ast.Name)):
			exit ('Complex for loops are not supported')

		self.write ('for (')
		self.visit (target)
		self.ostream.write (' of __iter__ (')
		prev = self.in_exp
		self.in_exp = True
		self.visit (iter)
		self.in_exp = prev

		self.ostream.write (')) {\n')
		self.inc_jslineno ()

		self.indent_level += 1
		for stmt in body:
			self.visit (stmt)
		self.indent_level -= 1

		self.write ('}\n')
		self.inc_jslineno ()

	def indent (self): self.indent_level += 1
	def unindent (self):
		self.indent_level -= 1
		if (self.indent_level < 0): raise Exception ('unindent () called unnecessarily')

	def inc_jslineno (self):
		self.jslineno += 1
		self.linemap [self.jslineno] = self.curr_lineno
	def visit_Break (self, node):
		self.write ('break')
		self.write_endline ()
	def visit_Continue (self, node):
		self.write ('continue')
		self.write_endline ()
	# FunctionDef
	def visit_FunctionDef (self, node):
		name, args, body = node.name, node.args, node.body
		self.curr_lineno = node.lineno
		start_lineno = self.jslineno
		self.write (f'{self.scope}.{name}')

		if (self.substitute is not None):
			self.ostream.write (' = ')
			self.ostream.write (''.join (self.substitute[name]))
			self.ostream.write (';\n')
			self.inc_jslineno ()
			return

		visitor = FuncVisitor (node)
		global_vars, local_vars = visitor.get_gl_vars ()

		self.ostream.write (f' = new __PyFunction__ (\'{name}\',')
		self.visit_params (args)
		self.ostream.write (' , function (')
		self.visit (args)

		# self.scope += ''
		self.ostream.write (') {\n')
		self.inc_jslineno ()

		self.indent_level += 1
		self.write ('let __globalvars__ = {')
		for lv in global_vars:
			self.ostream.write (f"'{lv}' : true, ")
		self.ostream.write ('};\n')
		self.inc_jslineno ()

		self.write ('let __localvars__ = {')
		for lv in local_vars:
			self.ostream.write (f"'{lv}' : true, ")
		self.ostream.write ('};\n')
		self.inc_jslineno ()

		self.write (f'let {self.scope}_ = __getfuncscope__ ({self.scope}, __globalvars__, __localvars__);\n')
		self.inc_jslineno ()
		prev = self.global_vars.copy()

		current_scope = self.scope
		self.scope += '_'
		self.write_args (args)
		for stmt in body:
			self.visit (stmt)
		self.scope = current_scope
		self.ostream.write ('return __PyNone__;\n')
		self.inc_jslineno ()
		self.ostream.write ('});\n')

		self.write (f'__symbolmap__.{name} = [{start_lineno}, {self.jslineno}]\n')
		self.inc_jslineno ()
		self.inc_jslineno ()

		self.global_vars = prev
		self.indent_level -= 1

	def visit_params (self, node):
		args, defaults = node.args, node.defaults
		prev = self.in_exp
		self.in_exp = True
		self.ostream.write ('[')
		for arg in args:
			self.ostream.write ('\'')
			self.visit (arg)
			self.ostream.write ('\'')
			self.ostream.write (', ')
		self.ostream.write ('], ')

		self.ostream.write ('[')
		for defarg in defaults:
			self.visit (defarg)
			self.ostream.write (', ')
		self.ostream.write (']')
		self.in_exp = prev

	def visit_arguments (self, node):
		args, defaults = node.args, node.defaults
		v = []
		if (len (args) > len (defaults)):
			for arg in args[0: (len(args) - len (defaults))]:
				v.append ((arg, ))
		for i in zip (args[(len(args) - len (defaults)) : ], defaults):
			v.append (i)

		for e in v:
			self.visit (e[0])
			if (len (e) != 1):
				self.ostream.write (' = ')
				self.visit (e[1])
			self.ostream.write (', ')

	def visit_arg (self, node):
		arg = node.arg
		self.ostream.write (arg)

	def visit_Global (self, node):
		for name in node.names:
			self.global_vars.append (name)

	def visit_Return (self, node):
		self.curr_lineno = node.lineno

		value = node.value
		prev = self.in_exp
		self.in_exp = True
		self.write ('return ')
		self.visit (value)
		self.in_exp = prev
		self.write_endline ()

	def visit_Pass (self, node): pass

	# imports
	def visit_Import (self, node):
		names = node.names

		for alias in names:
			name, asname = alias.name, alias.asname
			try:
				file = open (f'modules/{name}.py')
			except Exception as e:
				file = open (f'{name}.py')

			if (name == 'HAL'):
				if(emulateDir):
					subfile = 'eshim.json'
				else:
					subfile = 'shim.json'
			else: subfile = None

			if (asname != None) : name = asname
			self.write (f'let {self.scope}{name} = Object.assign (' + '{}' + ', __global__);' + '\n' + 'var emulateDir="'+emulateDir+'";\n')
			self.write (f'{self.scope}.{name} = new __PyModule__ (\'{name}\', {self.scope}{name});\n')
			# self.write (f'{self.scope} = ')
			pt = ast.parse (file.read ())

			Visitor (self.ostream, scope = f'{self.scope}{name}', subfile=subfile).visit (pt)
			# except Exception as e:
			# 	print (e)
			# 	# Not an inbuilt module. Try searching in the local dir instead.
			# 	self.write ('throw new __PyModuleNotFoundError__ (`No module named \'' + str (name) + '\'`);\n')


	# Exception Handling
	def visit_Raise (self, node):
		exc = node.exc
		prev_in_exp = self.in_exp
		self.in_exp = True
		self.write ('__raise__ (')
		self.visit (exc)
		self.ostream.write (');\n')
		self.inc_jslineno ()
		self.in_exp = prev_in_exp

	def visit_Try (self, node):
		body, handlers = node.body, node.handlers
		self.curr_lineno = node.lineno
		self.write ('try {')
		self.indent ()
		for stmt in body: self.visit (stmt)
		self.unindent ()
		self.write ('}')

		self.write ('catch (e) {\n')
		self.inc_jslineno ()
		self.indent ()
		if handlers is not None :
			for handler in handlers: self.visit (handler)
		self.write ('else {\n')
		self.inc_jslineno ()
		self.indent ()
		self.write ('throw e;\n')
		self.inc_jslineno ()
		self.unindent ()
		self.write ('}')

		self.unindent ()
		self.write ('};\n')
		self.inc_jslineno ()

	def visit_ExceptHandler (self, node):
		type, name, body = node.type, node.name, node.body
		if (type is None and name is None):
			for stmt in body: self.visit (stmt)
			return
		self.write ('if (__isexception__ (e)) {\n')
		self.inc_jslineno ()

		self.indent ()
		self.write ('if (e instanceof ')
		self.visit (type)
		self.ostream.write (') {\n')
		self.inc_jslineno ()
		self.indent ()
		self.write (f'{self.scope}.{name} = e;\n')
		self.inc_jslineno ()
		for stmt in body : self.visit (stmt)
		self.unindent ()
		self.write ('}\n')
		self.inc_jslineno ()
		self.unindent ();
		self.write ('}\n')
		self.inc_jslineno ()

	def visit_alias (self, node): pass

	# utility functions
	def write_lineno (self):
		self.ostream.write (f'/* {self.curr_lineno} */')
	def write (self, stmt):
		self.write_lineno ()
		self.write_indent()
		self.ostream.write (stmt)
	def write_indent (self):
		for i in range (0, self.indent_level):
			self.ostream.write ('\t')
	def write_args (self, node):
		for arg in node.args:
			self.write (f'{self.scope}.{arg.arg} = {arg.arg}')
			self.write_endline ()
	def write_endline (self):
		self.inc_jslineno ()
		self.ostream.write (f'; // {self.jslineno}\n')
	def write_statement (self, statement):
		self.write_indent ()
		self.ostream.write (statement + '\n')

if __name__ == '__main__':
	parser = argparse.ArgumentParser ()
	parser.add_argument("--emulatedir", dest='emulateDir', help="activate emulated input from files in dir")
	parser.add_argument ('inputfile', help = 'name of the input python file')
	parser.add_argument ('--outfile', help = 'name of the output js file', default = '__gen__.js')
	args = parser.parse_args ()
	emulateDir=os.path.abspath(args.emulateDir)
	try:
		f = open (args.inputfile, 'r')
	except Exception as e:
		print (f'\'{sys.argv[1]}\': No such file')
		exit ()
	pt = ast.parse (f.read ());
	f = io.StringIO();
	init = '''
	let handler = {
		get (target, key, recv) {
			if (! (key in target)) {
				throw new __PyNameError__ (`name '${key}' is not defined`);
			}
			return target[key];
		}
	};
	let __global__ = new Proxy (
	{int : __PyInt__, float : __PyFloat__, bool : __PyBool__, str : __PyStr__, len : len,
	print : print, range : __PyRange__, object : __PyObject__, type : __PyType__,
	slice : __PySlice__, dict : __PyDict__,

	BaseException : __PyBaseException__, Exception : __PyException__,
	TypeError : __PyTypeError__, NameError: __PyNameError__,
	UnboundLocalError : __PyUnboundLocalError__, IndexError : __PyIndexError__,
	ValueError : __PyValueError__, ZeroDivisionError : __PyZeroDivisionError__,
	AttributeError : __PyAttributeError__, ModuleNotFoundError : __PyModuleNotFoundError__,


	}, handler);
let __scope__ = Object.assign ({}, __global__);
__scope__ = new Proxy (__scope__, handler);
'''
	v = Visitor (f, init = init)
	v.visit (pt);
	# print (v.linemap)
	fp = open (args.outfile, 'w')
	try:
		fr = open ('runtime.js', 'r')
	except Exception as e:
		os.system ('python3 build_runtime.py')
		fr = open ('runtime.js', 'r')

	fp.write (fr.read())
	fp.write ('\n//Translated code below\ntry {\n')
	fp.write (f'__linemap__ = {str (v.linemap)}\n') # linemap
	fp.write (f.getvalue())
	fp.write ('} catch (e) {\nif (e instanceof Error) {\nconsole.log (e);\n} else {\ndecodecallstack (__callstack__);\nprint.__call__ (e);\n}}')
	# print (f.getvalue ());
